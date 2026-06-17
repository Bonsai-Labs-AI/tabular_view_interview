"""Celery tasks.

Tasks are sync at the Celery boundary. We keep a single long-lived asyncio
event loop per worker process and submit coroutines to it via
`run_coroutine_threadsafe`. Using `asyncio.run` per-task instead would
trigger 'Event loop is closed' errors on subsequent tasks because the
AsyncOpenAI httpx client retains references to the prior loop.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from .queue import celery_app
from .workers.cell_worker import fill_cell

_log = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a single long-lived loop for this worker process, lazily started."""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, daemon=True)
            t.start()
        return _loop


@celery_app.task(name="cells.fill", bind=True)
def fill_cell_task(self, cell_id: str) -> None:
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(fill_cell(cell_id), loop)
    try:
        future.result()
    except Exception:
        _log.exception("fill_cell_task failed for cell %s", cell_id)
        raise
