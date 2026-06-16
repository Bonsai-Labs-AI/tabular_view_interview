import asyncio
import json
import logging
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .. import sse
from ..config import settings
from ..database import async_session
from ..models import Cell, Document, Row, Table, TableColumn
from ..rag.search import semantic_search

MAX_SEARCH_ITERATIONS = 3
MAX_CELL_RETRIES = 2
MAX_SUBAGENT_TURNS = 12
_WEB_SEARCH_TIMEOUT = 20  # seconds for a single Tavily call

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _AnswerSource(BaseModel):
    title: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)


class _AnswerPayload(BaseModel):
    answer: str = Field(..., min_length=1)
    confidence: Literal["low", "medium", "high"]
    reasoning: str = Field(..., min_length=1)
    sources: list[_AnswerSource] = Field(..., min_length=1)


class _SubagentFindings(BaseModel):
    summary: str = Field(..., min_length=1)
    sources: list[_AnswerSource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool primitives
# ---------------------------------------------------------------------------

async def _web_search(query: str) -> list[dict]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=settings.tavily_api_key)
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                client.search, query, max_results=3, search_depth="basic"
            ),
            timeout=_WEB_SEARCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        _log.warning("Web search timed out for query: %s", query)
        return []
    return [
        {"title": r["title"], "url": r["url"], "content": r["content"]}
        for r in results.get("results", [])
    ]


async def _read_document(arbitrator_id: str, doc_type: str) -> str | None:
    async with async_session() as db:
        result = await db.execute(
            select(Document).where(
                Document.arbitrator_id == arbitrator_id,
                Document.doc_type == doc_type,
            )
        )
        doc = result.scalar_one_or_none()
        return doc.content if doc else None


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_WEB_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search for information about the arbitrator from web sources.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

_READ_DOCUMENT_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "read_document",
        "description": "Search for information about the arbitrator from their document records.",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_type": {
                    "type": "string",
                    "enum": [
                        "cv",
                        "opinion_or_award",
                        "news_article",
                        "interview_transcript",
                        "panel_announcement",
                    ],
                },
            },
            "required": ["doc_type"],
        },
    },
}

_SUBMIT_FINDINGS_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "submit_findings",
        "description": "Submit your research findings",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["summary", "sources"],
        },
    },
}

_SUBMIT_ANSWER_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Submit the final researched answer for this cell",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "reasoning": {"type": "string"},
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["answer", "confidence", "reasoning", "sources"],
        },
    },
}

_SEMANTIC_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "semantic_search",
        "description": (
            "Semantic search over the arbitrator's document corpus. Returns the "
            "top-k most relevant chunks across all of their documents (CV, opinions, "
            "news articles, transcripts, panel announcements, and any other files in "
            "the corpus). Use this when you don't know which document to read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {
                    "type": "integer",
                    "description": "Number of chunks to return (default 5, max 10).",
                },
            },
            "required": ["query"],
        },
    },
}

_WEB_SUBAGENT_TOOLS: list[Any] = [_WEB_SEARCH_TOOL, _SUBMIT_FINDINGS_TOOL]
_DOC_SUBAGENT_TOOLS: list[Any] = [
    _SEMANTIC_SEARCH_TOOL,
    _READ_DOCUMENT_TOOL,
    _SUBMIT_FINDINGS_TOOL,
]


# ---------------------------------------------------------------------------
# Shared subagent loop runner
# ---------------------------------------------------------------------------

async def _run_subagent(
    client: AsyncOpenAI,
    system: str,
    user: str,
    arbitrator_id: str,
    *,
    tools: list[Any],
) -> _SubagentFindings:
    messages: list[Any] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    search_count = 0

    for _turn in range(MAX_SUBAGENT_TURNS):
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            tools=tools,
        )
        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            content = msg.content or "No findings."
            return _SubagentFindings(summary=content, sources=[])

        tool_results: list[Any] = []
        submitted: _SubagentFindings | None = None
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)

            if tc.function.name == "submit_findings":
                submitted = _SubagentFindings.model_validate(args)
                break

            if tc.function.name == "web_search":
                if search_count >= MAX_SEARCH_ITERATIONS:
                    content = "Web search limit reached. Call submit_findings now."
                else:
                    results = await _web_search(args["query"])
                    search_count += 1
                    content = "\n\n".join(
                        f"**{r['title']}**\n{r['url']}\n{r['content']}"
                        for r in results
                    )
                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": content}
                )
            elif tc.function.name == "semantic_search":
                k = min(int(args.get("k", 5)), 10)
                hits = await semantic_search(arbitrator_id, args["query"], k=k)
                if not hits:
                    content = "No matching chunks found in the corpus."
                else:
                    content = "\n\n---\n\n".join(
                        f"**{h['filename']}** (score={h['score']:.2f})\n{h['chunk']}"
                        for h in hits
                    )
                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": content}
                )
            elif tc.function.name == "read_document":
                doc_content = await _read_document(arbitrator_id, args["doc_type"])
                if doc_content is None:
                    content = (
                        f"No document of type '{args['doc_type']}' available. "
                        "Try a different doc_type."
                    )
                else:
                    content = doc_content
                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": content}
                )
            else:
                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": "Unknown tool."}
                )

        if submitted is not None:
            return submitted

        messages.extend(tool_results)

        if search_count >= MAX_SEARCH_ITERATIONS:
            forced = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                tools=tools,
                tool_choice={
                    "type": "function",
                    "function": {"name": "submit_findings"},
                },
            )
            forced_calls = forced.choices[0].message.tool_calls or []
            if not forced_calls:
                return _SubagentFindings(
                    summary="Search limit reached and no findings could be extracted.",
                    sources=[],
                )
            return _SubagentFindings.model_validate(
                json.loads(forced_calls[0].function.arguments)
            )

    return _SubagentFindings(
        summary="Subagent exceeded turn budget without submitting findings.",
        sources=[],
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

async def _run_planner(
    client: AsyncOpenAI,
    arbitrator_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
    research_goal: str,
) -> str:
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You plan research strategies for a comparison table. Be brief.",
            },
            {
                "role": "user",
                "content": (
                    f"Research goal: {research_goal}\n"
                    f"Arbitrator: {arbitrator_name}\n"
                    f"Column to fill: {column_name} ({output_type})\n"
                    f"Column description: {column_description}\n\n"
                    "Output a brief plan (2-3 sentences): which sources should we consult "
                    "(web, documents, or both)? What specific things to look for?"
                ),
            },
        ],
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Web search + document analysis subagents
# ---------------------------------------------------------------------------

async def _run_web_subagent(
    client: AsyncOpenAI,
    plan: str,
    arbitrator_id: str,
    arbitrator_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
) -> _SubagentFindings:
    system = (
        "You are a web search specialist. Find information about the arbitrator from "
        "web sources.\n\n"
        f"Plan from coordinator:\n{plan}"
    )
    user = (
        f"Arbitrator: {arbitrator_name}\n"
        f"Column: {column_name} ({output_type}) - {column_description}\n\n"
        f"Use web_search (up to {MAX_SEARCH_ITERATIONS} queries), then submit_findings."
    )
    return await _run_subagent(
        client, system, user, arbitrator_id, tools=_WEB_SUBAGENT_TOOLS
    )


async def _run_doc_subagent(
    client: AsyncOpenAI,
    plan: str,
    arbitrator_id: str,
    arbitrator_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
) -> _SubagentFindings:
    system = (
        "You are a document analysis specialist. Find information about the arbitrator "
        "from their indexed document corpus.\n\n"
        f"Plan from coordinator:\n{plan}"
    )
    user = (
        f"Arbitrator: {arbitrator_name}\n"
        f"Column: {column_name} ({output_type}) - {column_description}\n\n"
        "Use semantic_search to find relevant chunks across the corpus. If a "
        "chunk looks promising and you want more context, use read_document with "
        "the appropriate doc_type. Then submit_findings."
    )
    return await _run_subagent(
        client, system, user, arbitrator_id, tools=_DOC_SUBAGENT_TOOLS
    )


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

async def _run_synthesis(
    client: AsyncOpenAI,
    web_findings: _SubagentFindings,
    doc_findings: _SubagentFindings,
    arbitrator_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
) -> dict:
    summaries_text = (
        f"Web findings: {web_findings.summary}\n\n"
        f"Document findings: {doc_findings.summary}"
    )
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You synthesize research findings into a final answer for a "
                    "comparison table cell."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Arbitrator: {arbitrator_name}\n"
                    f"Column: {column_name} ({output_type}) - {column_description}\n\n"
                    f"{summaries_text}\n\n"
                    "Call submit_answer with the final answer."
                ),
            },
        ],
        tools=[_SUBMIT_ANSWER_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_answer"}},
    )
    tool_calls = response.choices[0].message.tool_calls or []
    if not tool_calls:
        raise RuntimeError("Synthesis model did not call submit_answer.")
    return _AnswerPayload.model_validate(
        json.loads(tool_calls[0].function.arguments)
    ).model_dump()


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

async def _run_agent(
    arbitrator_id: str,
    row_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
    research_goal: str,
) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    plan = await _run_planner(
        client,
        arbitrator_name=row_name,
        column_name=column_name,
        column_description=column_description,
        output_type=output_type,
        research_goal=research_goal,
    )

    web_findings = await _run_web_subagent(
        client,
        plan=plan,
        arbitrator_id=arbitrator_id,
        arbitrator_name=row_name,
        column_name=column_name,
        column_description=column_description,
        output_type=output_type,
    )
    doc_findings = await _run_doc_subagent(
        client,
        plan=plan,
        arbitrator_id=arbitrator_id,
        arbitrator_name=row_name,
        column_name=column_name,
        column_description=column_description,
        output_type=output_type,
    )

    return await _run_synthesis(
        client,
        web_findings=web_findings,
        doc_findings=doc_findings,
        arbitrator_name=row_name,
        column_name=column_name,
        column_description=column_description,
        output_type=output_type,
    )


# ---------------------------------------------------------------------------
# Public entry-point - called once per cell via asyncio.create_task()
# ---------------------------------------------------------------------------

async def fill_cell(cell_id: str, _retries: int = MAX_CELL_RETRIES) -> None:
    try:
        async with async_session() as db:
            cell = await db.get(Cell, cell_id)
            if cell is None or cell.status in ("working", "done"):
                return

            row = await db.get(Row, cell.row_id)
            table = await db.get(Table, cell.table_id)
            column = await db.get(TableColumn, cell.column_id)
            if row is None or table is None or column is None:
                _log.error(
                    "Cell %s has missing row/table/column references; marking failed",
                    cell_id,
                )
                cell.status = "failed"
                await db.commit()
                return

            table_id = cell.table_id
            row_id = row.id
            column_id = cell.column_id
            arbitrator_id = row.arbitrator_id
            row_name = row.name
            column_name = column.name
            column_description = column.description
            column_output_type = column.output_type
            research_goal = table.research_goal

            cell.status = "working"
            await db.commit()

        await sse.publish(
            table_id,
            {"type": "cell_working", "rowId": row_id, "columnId": column_id},
        )

        result = await _run_agent(
            arbitrator_id=arbitrator_id,
            row_name=row_name,
            column_name=column_name,
            column_description=column_description,
            output_type=column_output_type,
            research_goal=research_goal,
        )

        async with async_session() as db:
            cell = await db.get(Cell, cell_id)
            if cell is None:
                return
            cell.status = "done"
            cell.value = result.get("answer", "")
            cell.confidence = result.get("confidence", "low")
            cell.reasoning = result.get("reasoning", "")
            cell.sources = result.get("sources", [])
            await db.commit()

            done_payload = {
                "type": "cell_done",
                "rowId": row_id,
                "columnId": column_id,
                "value": cell.value,
                "confidence": cell.confidence,
                "sources": cell.sources or [],
            }

        await sse.publish(table_id, done_payload)

    except Exception as exc:
        if _retries > 0:
            _log.warning("Transient failure for cell %s, retrying (%d left): %r", cell_id, _retries, exc)
            # Reset status so the next attempt isn't blocked by the
            # "already working" guard at the top of fill_cell.
            try:
                async with async_session() as db:
                    cell = await db.get(Cell, cell_id)
                    if cell is not None and cell.status == "working":
                        cell.status = "pending"
                        await db.commit()
            except SQLAlchemyError:
                _log.exception("Could not reset cell %s status before retry", cell_id)
            await asyncio.sleep(1)
            return await fill_cell(cell_id, _retries=_retries - 1)
        _log.error("Cell %s failed terminally: %r", cell_id, exc)
        try:
            async with async_session() as db:
                cell = await db.get(Cell, cell_id)
                if cell:
                    cell.status = "failed"
                    await db.commit()
                    await sse.publish(
                        cell.table_id,
                        {
                            "type": "cell_failed",
                            "rowId": cell.row_id,
                            "columnId": cell.column_id,
                            "error": str(exc),
                        },
                    )
        except SQLAlchemyError:
            _log.exception("Failed to record terminal failure for cell %s", cell_id)
