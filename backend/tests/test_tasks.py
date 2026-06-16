"""Tests for the Celery task wrapper.

The task is sync; it asyncio.run()s the async fill_cell coroutine. We test
that this glue is correct by patching fill_cell.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app import tasks


def test_fill_cell_task_runs_async_fill_cell():
    """The sync Celery task should drive fill_cell to completion."""
    invocations: list[str] = []

    async def fake_fill(cell_id: str) -> None:
        invocations.append(cell_id)

    with patch("app.tasks.fill_cell", side_effect=fake_fill):
        # Run the underlying function directly (bypassing Celery dispatch).
        tasks.fill_cell_task.run("cell-xyz")

    assert invocations == ["cell-xyz"]


def test_fill_cell_task_propagates_exception():
    async def boom(cell_id: str) -> None:
        raise RuntimeError("kaboom")

    with patch("app.tasks.fill_cell", side_effect=boom):
        with pytest.raises(RuntimeError, match="kaboom"):
            tasks.fill_cell_task.run("cell-xyz")
