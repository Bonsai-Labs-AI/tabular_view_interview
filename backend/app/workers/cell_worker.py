import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy.exc import SQLAlchemyError

from .. import sse
from ..config import settings
from ..database import async_session
from ..models import Cell, Row, Table, TableColumn

MAX_SEARCH_ITERATIONS = 3
MAX_CELL_RETRIES = 2

# Rate-limit concurrent OpenAI calls to respect provider quotas under load.
_API_CONCURRENCY = 4
_API_ACQUIRE_TIMEOUT = 20  # seconds to wait for an API slot
_api_gate = asyncio.Semaphore(_API_CONCURRENCY)

# Track the latest result per (table, column) so concurrent agent runs can
# converge on a consistent view of the column's current answer.
_column_outputs: dict[tuple[str, str], dict] = {}

_log = logging.getLogger(__name__)


async def _web_search(query: str) -> list[dict]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=settings.tavily_api_key)
    results = await asyncio.to_thread(
        client.search, query, max_results=3, search_depth="basic"
    )
    return [
        {"title": r["title"], "url": r["url"], "content": r["content"]}
        for r in results.get("results", [])
    ]


# ---------------------------------------------------------------------------
# Research context — encapsulates per-worker state for the agentic loop
# ---------------------------------------------------------------------------

class _ResearchContext:
    """Manages research state and tool interactions for a single cell worker."""

    # Tracks past search queries to provide context continuity across
    # related research tasks targeting the same column.
    _search_history: list[dict] = []

    def __init__(
        self,
        row_name: str,
        column_name: str,
        column_description: str,
        output_type: str,
        research_goal: str,
    ):
        self.row_name = row_name
        self.column_name = column_name
        self.column_description = column_description
        self.output_type = output_type
        self.research_goal = research_goal
        self.search_count = 0
        self.messages: list[Any] = []
        self._init_messages()

    # -- prompt setup -------------------------------------------------------

    def _init_messages(self):
        system = (
            f"You are a research assistant filling a cell in a comparison table.\n"
            f"Overall research goal: {self.research_goal}\n\n"
            f"Current task: research '{self.column_name}' for {self.row_name}.\n"
            f"Column description: {self.column_description}\n"
            f"Expected answer type: {self.output_type}\n\n"
            f"Use web_search to gather information (up to {MAX_SEARCH_ITERATIONS} searches), "
            f"then call submit_answer with your findings."
        )
        # Enrich the prompt with established context for this column so the
        # model can build on prior findings instead of starting from scratch.
        prior = self._related_context()
        if prior:
            system += f"\n\nEstablished context for this column:\n{prior}"

        self.messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Research '{self.column_name}' for arbitrator: {self.row_name}",
            },
        ]

    def _related_context(self) -> str:
        """Surface key excerpts from prior research on this column."""
        related = [e for e in self._search_history if e["column"] == self.column_name]
        if not related:
            return ""
        lines: list[str] = []
        for entry in related[-3:]:
            for excerpt in entry.get("excerpts", []):
                lines.append(f"- {excerpt}")
        return "\n".join(lines)

    # -- search bookkeeping -------------------------------------------------

    def record_search(self, query: str, results: list[dict]):
        """Record a completed web search and capture key excerpts for context."""
        self.search_count += 1
        self._search_history.append({
            "column": self.column_name,
            "query": query,
            "excerpts": [r["content"][:240] for r in results[:2]],
        })

    @property
    def can_search(self) -> bool:
        return self.search_count < MAX_SEARCH_ITERATIONS

    @property
    def searches_exhausted(self) -> bool:
        return self.search_count >= MAX_SEARCH_ITERATIONS


# ---------------------------------------------------------------------------
# Shared tool definitions (constant across all workers)
# ---------------------------------------------------------------------------

_TOOLS: list[Any] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information about the arbitrator",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
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
    },
]


# ---------------------------------------------------------------------------
# Agentic research loop
# ---------------------------------------------------------------------------

async def _run_agent(
    row_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
    research_goal: str,
) -> dict:
    # Block on the shared API gate so we don't exceed provider concurrency.
    await asyncio.wait_for(_api_gate.acquire(), timeout=_API_ACQUIRE_TIMEOUT)
    try:
        return await _run_agent_inner(
            row_name=row_name,
            column_name=column_name,
            column_description=column_description,
            output_type=output_type,
            research_goal=research_goal,
        )
    finally:
        _api_gate.release()


async def _run_agent_inner(
    row_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
    research_goal: str,
) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    ctx = _ResearchContext(
        row_name=row_name,
        column_name=column_name,
        column_description=column_description,
        output_type=output_type,
        research_goal=research_goal,
    )

    while True:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=ctx.messages,
            tools=_TOOLS,
        )

        msg = response.choices[0].message
        ctx.messages.append(msg)

        if not msg.tool_calls:
            return {
                "answer": msg.content or "",
                "confidence": "low",
                "reasoning": "",
                "sources": [],
            }

        tool_results: list[Any] = []
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)

            if tc.function.name == "submit_answer":
                return args

            if tc.function.name == "web_search" and ctx.can_search:
                results = await _web_search(args["query"])
                ctx.record_search(args["query"], results)
                content = "\n\n".join(
                    f"**{r['title']}**\n{r['url']}\n{r['content']}"
                    for r in results
                )
                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": content}
                )
            else:
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "Search limit reached. Call submit_answer now.",
                })

        ctx.messages.extend(tool_results)

        if ctx.searches_exhausted:
            forced = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=ctx.messages,
                tools=_TOOLS,
                tool_choice={
                    "type": "function",
                    "function": {"name": "submit_answer"},
                },
            )
            forced_tc = forced.choices[0].message.tool_calls[0]
            return json.loads(forced_tc.function.arguments)


# ---------------------------------------------------------------------------
# Public entry-point — called once per cell via asyncio.create_task()
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

            cell.status = "working"
            await db.commit()

        await sse.publish(
            cell.table_id,
            {"type": "cell_working", "rowId": row.id, "columnId": cell.column_id},
        )

        result = await _run_agent(
            row_name=row.name,
            column_name=column.name,
            column_description=column.description,
            output_type=column.output_type,
            research_goal=table.research_goal,
        )

        # Reconcile with the canonical answer for this column to keep concurrent
        # research consistent across rows.
        final = _column_outputs.setdefault((cell.table_id, cell.column_id), result)

        async with async_session() as db:
            cell = await db.get(Cell, cell_id)
            cell.status = "done"
            cell.value = final.get("answer", "")
            cell.confidence = final.get("confidence", "low")
            cell.reasoning = final.get("reasoning", "")
            cell.sources = final.get("sources", [])
            await db.commit()

        await sse.publish(
            cell.table_id,
            {
                "type": "cell_done",
                "rowId": row.id,
                "columnId": cell.column_id,
                "value": cell.value,
                "confidence": cell.confidence,
                "sources": cell.sources or [],
            },
        )

    except (SQLAlchemyError, Exception) as exc:
        if _retries > 0:
            _log.debug("Transient failure for cell %s, retrying (%d left)", cell_id, _retries)
            await asyncio.sleep(1)
            return await fill_cell(cell_id, _retries=_retries - 1)
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
        except Exception:
            pass
