"""Redis pub/sub bridge for server-sent events.

Cell workers run in separate Celery worker processes, so SSE events must
travel out-of-process. We use a Redis pub/sub channel per table_id.

Public API mirrors the old in-process module so callers don't change:
- `publish(table_id, event)` — fire-and-forget publish from any process
- `subscribe(table_id)` — async context manager yielding a PubSub object the
  caller can iterate with `get_message`
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from .config import settings


_CHANNEL_PREFIX = "table-events"

_client: Optional[Redis] = None


def _channel(table_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{table_id}"


def get_redis() -> Redis:
    """Module-level lazy singleton. Tests monkeypatch this to inject fakeredis."""
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def publish(table_id: str, event: dict) -> None:
    client = get_redis()
    await client.publish(_channel(table_id), json.dumps(event))


@asynccontextmanager
async def subscribe(table_id: str) -> AsyncIterator[PubSub]:
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(_channel(table_id))
    # Drain the subscribe ack so callers using get_message with
    # ignore_subscribe_messages=True don't see a spurious None on first read.
    await pubsub.get_message(timeout=1.0)
    try:
        yield pubsub
    finally:
        try:
            await pubsub.unsubscribe(_channel(table_id))
        finally:
            await pubsub.aclose()


async def reset_client() -> None:
    """Drop the cached client. Used in tests between cases."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
