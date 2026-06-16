"""Table-level workflow coordination.

Owns the "start this table" decision: which cells are pending, enqueue them,
flip the table status. Routes call into here so the dispatch path has a
single seam tests can monkeypatch.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Cell, Table


async def select_pending_cell_ids(db: AsyncSession, table_id: str) -> list[str]:
    result = await db.execute(
        select(Cell.id).where(Cell.table_id == table_id, Cell.status == "pending")
    )
    return [row for row in result.scalars().all()]


def enqueue_cell(cell_id: str) -> None:
    """Single dispatch seam. Tests monkeypatch this to run inline."""
    from .tasks import fill_cell_task

    fill_cell_task.delay(cell_id)


def enqueue_cells(cell_ids: Iterable[str]) -> int:
    count = 0
    for cell_id in cell_ids:
        enqueue_cell(cell_id)
        count += 1
    return count


async def start_table(db: AsyncSession, table: Table) -> int:
    """Dispatch all pending cells for the table and flip it to running.

    Returns the number of cells dispatched.
    """
    cell_ids = await select_pending_cell_ids(db, table.id)
    enqueue_cells(cell_ids)
    table.status = "running"
    await db.commit()
    return len(cell_ids)
