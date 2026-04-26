import asyncio
import json
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .. import sse
from ..config import settings
from ..database import async_session
from ..models import Cell, Row, Table, TableColumn

MAX_SEARCH_ITERATIONS = 3


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


async def _run_agent(
    row_name: str,
    column_name: str,
    column_description: str,
    output_type: str,
    research_goal: str,
) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    system = (
        f"You are a research assistant filling a cell in a comparison table.\n"
        f"Overall research goal: {research_goal}\n\n"
        f"Current task: research '{column_name}' for {row_name}.\n"
        f"Column description: {column_description}\n"
        f"Expected answer type: {output_type}\n\n"
        f"Use web_search to gather information (up to {MAX_SEARCH_ITERATIONS} searches), "
        f"then call submit_answer with your findings."
    )

    tools: list[Any] = [
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
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
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

    messages: list[Any] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Research '{column_name}' for arbitrator: {row_name}"},
    ]
    search_count = 0

    while True:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            tools=tools,
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return {"answer": msg.content or "", "confidence": "low", "reasoning": "", "sources": []}

        tool_results: list[Any] = []
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)

            if tc.function.name == "submit_answer":
                return args

            if tc.function.name == "web_search" and search_count < MAX_SEARCH_ITERATIONS:
                search_count += 1
                results = await _web_search(args["query"])
                content = "\n\n".join(
                    f"**{r['title']}**\n{r['url']}\n{r['content']}" for r in results
                )
                tool_results.append({"role": "tool", "tool_call_id": tc.id, "content": content})
            else:
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "Search limit reached. Call submit_answer now.",
                })

        messages.extend(tool_results)

        if search_count >= MAX_SEARCH_ITERATIONS:
            forced = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "submit_answer"}},
            )
            forced_tc = forced.choices[0].message.tool_calls[0]
            return json.loads(forced_tc.function.arguments)


async def fill_cell(cell_id: str) -> None:
    try:
        async with async_session() as db:
            cell = await db.get(Cell, cell_id)
            if cell is None:
                return

            row = await db.get(Row, cell.row_id)
            table = await db.get(Table, cell.table_id)

            # Resolve column via name match — breaks if column has been renamed
            col_result = await db.execute(
                select(TableColumn).where(
                    TableColumn.table_id == cell.table_id,
                    TableColumn.name == cell.column_name,
                )
            )
            column = col_result.scalar_one_or_none()
            column_id = column.id if column else cell.column_name

            cell.status = "working"
            await db.commit()

        await sse.publish(
            cell.table_id,
            {"type": "cell_working", "rowId": row.id, "columnId": column_id},
        )

        result = await _run_agent(
            row_name=row.name,
            column_name=cell.column_name,
            column_description=column.description if column else "",
            output_type=column.output_type if column else "short_text",
            research_goal=table.research_goal,
        )

        async with async_session() as db:
            cell = await db.get(Cell, cell_id)
            cell.status = "done"
            cell.value = result.get("answer", "")
            cell.confidence = result.get("confidence", "low")
            cell.reasoning = result.get("reasoning", "")
            cell.sources = result.get("sources", [])
            await db.commit()

        await sse.publish(
            cell.table_id,
            {
                "type": "cell_done",
                "rowId": row.id,
                "columnId": column_id,
                "value": cell.value,
                "confidence": cell.confidence,
                "sources": cell.sources or [],
            },
        )

    except (SQLAlchemyError, Exception) as exc:
        try:
            async with async_session() as db:
                cell = await db.get(Cell, cell_id)
                if cell:
                    cell.status = "failed"
                    await db.commit()
                    await sse.publish(
                        cell.table_id,
                        {"type": "cell_failed", "rowId": cell.row_id, "columnId": cell.column_name, "error": str(exc)},
                    )
        except Exception:
            pass
