"""Celery tasks.

Tasks are sync at the Celery boundary; we spin up a fresh asyncio loop per
task to drive the async cell_worker. Each task is its own process-isolated
unit of work, so there's no event loop reuse to worry about.
"""
from __future__ import annotations

import asyncio
import logging

from .queue import celery_app
from .workers.cell_worker import fill_cell

_log = logging.getLogger(__name__)


@celery_app.task(name="cells.fill", bind=True)
def fill_cell_task(self, cell_id: str) -> None:
    try:
        asyncio.run(fill_cell(cell_id))
    except Exception:
        _log.exception("fill_cell_task failed for cell %s", cell_id)
        raise
