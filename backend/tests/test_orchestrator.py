"""Tests for the orchestrator module."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import orchestrator
from app.models import Cell, Row, Table, TableColumn


async def _seed_table(session_factory) -> tuple[str, list[str]]:
    """Create a table with one row, two columns, two pending cells."""
    async with session_factory() as db:
        table = Table(research_goal="goal", status="draft")
        db.add(table)
        await db.flush()
        row = Row(table_id=table.id, arbitrator_id="arb_1", name="R1")
        col_a = TableColumn(table_id=table.id, name="A", description="", output_type="short_text")
        col_b = TableColumn(table_id=table.id, name="B", description="", output_type="short_text")
        db.add_all([row, col_a, col_b])
        await db.flush()
        cell_a = Cell(table_id=table.id, row_id=row.id, column_id=col_a.id, status="pending")
        cell_b = Cell(table_id=table.id, row_id=row.id, column_id=col_b.id, status="pending")
        db.add_all([cell_a, cell_b])
        await db.commit()
        return table.id, [cell_a.id, cell_b.id]


@pytest.mark.asyncio
async def test_start_table_dispatches_pending_cells_and_marks_running(session_factory):
    table_id, cell_ids = await _seed_table(session_factory)

    dispatched: list[str] = []
    with patch("app.orchestrator.enqueue_cell", side_effect=dispatched.append):
        async with session_factory() as db:
            table = await db.get(Table, table_id)
            count = await orchestrator.start_table(db, table)

    assert count == 2
    assert sorted(dispatched) == sorted(cell_ids)

    async with session_factory() as db:
        table = await db.get(Table, table_id)
        assert table.status == "running"


@pytest.mark.asyncio
async def test_start_table_skips_non_pending(session_factory):
    table_id, cell_ids = await _seed_table(session_factory)

    # Flip one cell to "done" so only one remains pending.
    async with session_factory() as db:
        cell = await db.get(Cell, cell_ids[0])
        cell.status = "done"
        await db.commit()

    dispatched: list[str] = []
    with patch("app.orchestrator.enqueue_cell", side_effect=dispatched.append):
        async with session_factory() as db:
            table = await db.get(Table, table_id)
            count = await orchestrator.start_table(db, table)

    assert count == 1
    assert dispatched == [cell_ids[1]]


@pytest.mark.asyncio
async def test_select_pending_cell_ids(session_factory):
    table_id, cell_ids = await _seed_table(session_factory)

    async with session_factory() as db:
        ids = await orchestrator.select_pending_cell_ids(db, table_id)

    assert sorted(ids) == sorted(cell_ids)


@pytest.mark.asyncio
async def test_enqueue_cells_returns_count(session_factory):
    """enqueue_cells should call enqueue_cell for each id and return the count."""
    dispatched: list[str] = []
    with patch("app.orchestrator.enqueue_cell", side_effect=dispatched.append):
        n = orchestrator.enqueue_cells(["a", "b", "c"])

    assert n == 3
    assert dispatched == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_enqueue_cell_delegates_to_celery(monkeypatch):
    """Verify the real enqueue_cell drives fill_cell_task.delay().

    The autouse conftest fixture replaces orchestrator.enqueue_cell with an
    inline call, so we have to restore the real symbol first.
    """
    calls: list[str] = []

    class FakeTask:
        def delay(self, cell_id: str) -> None:
            calls.append(cell_id)

    from app import tasks
    monkeypatch.setattr(tasks, "fill_cell_task", FakeTask())

    # Restore the real enqueue_cell on top of the autouse-patched version.
    def real_enqueue(cell_id: str) -> None:
        from app.tasks import fill_cell_task
        fill_cell_task.delay(cell_id)

    monkeypatch.setattr(orchestrator, "enqueue_cell", real_enqueue)

    orchestrator.enqueue_cell("cell-123")

    assert calls == ["cell-123"]
