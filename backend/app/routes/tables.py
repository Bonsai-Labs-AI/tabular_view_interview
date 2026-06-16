import asyncio
import json

from openai import AsyncOpenAI
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import orchestrator, sse
from ..config import settings
from ..database import get_db
from ..models import Cell, Row, Table, TableColumn
from ..schemas import (
    CellOut,
    ColumnDef,
    ColumnOut,
    CreateTableRequest,
    ProposeColumnsRequest,
    ProposeColumnsResponse,
    RenameColumnRequest,
    RowOut,
    TableOut,
)

router = APIRouter()

PREDEFINED_ROWS = [
    {"id": "arb_1", "name": "Prof. Eleanor Vance"},
    {"id": "arb_2", "name": "Hon. Michael Torres (Ret.)"},
    {"id": "arb_3", "name": "Dr. Amara Okonkwo"},
    {"id": "arb_4", "name": "James Whitfield, Esq."},
    {"id": "arb_5", "name": "Dr. Yuki Tanaka"},
]


@router.post("/propose-columns", response_model=ProposeColumnsResponse)
async def propose_columns(req: ProposeColumnsRequest):
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    arbitrator_names = [r["name"] for r in PREDEFINED_ROWS]

    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research goal: {req.research_goal}\n\n"
                    f"Arbitrators to compare: {', '.join(arbitrator_names)}\n\n"
                    "Propose 4–6 research columns for this comparison table. "
                    "Each column should be a distinct research dimension that can be investigated via web search."
                ),
            }
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "propose_columns",
                    "description": "Propose research columns for the arbitrator comparison table",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "columns": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "output_type": {
                                            "type": "string",
                                            "enum": ["short_text", "long_text", "boolean", "number", "date", "list"],
                                        },
                                        "required_evidence": {"type": "boolean"},
                                    },
                                    "required": ["name", "description", "output_type", "required_evidence"],
                                },
                                "minItems": 4,
                                "maxItems": 6,
                            }
                        },
                        "required": ["columns"],
                    },
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "propose_columns"}},
    )

    tc = response.choices[0].message.tool_calls[0]
    columns = [ColumnDef(**c) for c in json.loads(tc.function.arguments)["columns"]]
    return ProposeColumnsResponse(columns=columns)


@router.post("", response_model=TableOut)
async def create_table(req: CreateTableRequest, db: AsyncSession = Depends(get_db)):
    table = Table(research_goal=req.research_goal, status="draft")
    db.add(table)
    await db.flush()

    rows = []
    for r in PREDEFINED_ROWS:
        row = Row(table_id=table.id, arbitrator_id=r["id"], name=r["name"])
        db.add(row)
        rows.append(row)

    columns = []
    for col_def in req.columns:
        col = TableColumn(
            table_id=table.id,
            name=col_def.name,
            description=col_def.description,
            output_type=col_def.output_type,
            required_evidence=col_def.required_evidence,
        )
        db.add(col)
        columns.append(col)

    await db.flush()

    cells = []
    for row in rows:
        for col in columns:
            cell = Cell(
                table_id=table.id,
                row_id=row.id,
                column_id=col.id,
                status="pending",
            )
            db.add(cell)
            cells.append(cell)

    await db.commit()
    await db.refresh(table)

    return TableOut(
        id=table.id,
        research_goal=table.research_goal,
        status=table.status,
        rows=[RowOut.model_validate(r) for r in rows],
        columns=[ColumnOut.model_validate(c) for c in columns],
        cells=[CellOut.model_validate(c) for c in cells],
    )


@router.get("/{table_id}", response_model=TableOut)
async def get_table(table_id: str, db: AsyncSession = Depends(get_db)):
    table = await db.get(Table, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    rows_result = await db.execute(select(Row).where(Row.table_id == table_id))
    columns_result = await db.execute(select(TableColumn).where(TableColumn.table_id == table_id))
    cells_result = await db.execute(select(Cell).where(Cell.table_id == table_id))

    return TableOut(
        id=table.id,
        research_goal=table.research_goal,
        status=table.status,
        rows=[RowOut.model_validate(r) for r in rows_result.scalars()],
        columns=[ColumnOut.model_validate(c) for c in columns_result.scalars()],
        cells=[CellOut.model_validate(c) for c in cells_result.scalars()],
    )


@router.post("/{table_id}/start")
async def start_table(table_id: str, db: AsyncSession = Depends(get_db)):
    table = await db.get(Table, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    count = await orchestrator.start_table(db, table)
    return {"status": "started", "cell_count": count}


@router.patch("/{table_id}/columns/{column_id}", response_model=ColumnOut)
async def rename_column(
    table_id: str,
    column_id: str,
    req: RenameColumnRequest,
    db: AsyncSession = Depends(get_db),
):
    col = await db.get(TableColumn, column_id)
    if not col or col.table_id != table_id:
        raise HTTPException(status_code=404, detail="Column not found")
    col.name = req.name
    await db.commit()
    await db.refresh(col)
    return ColumnOut.model_validate(col)


@router.get("/{table_id}/events")
async def table_events(table_id: str):
    async def generate():
        async with sse.subscribe(table_id) as pubsub:
            while True:
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=30.0,
                    )
                except asyncio.CancelledError:
                    return
                if msg is None:
                    yield ": ping\n\n"
                    continue
                data = msg.get("data")
                if data is None:
                    continue
                yield f"data: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
