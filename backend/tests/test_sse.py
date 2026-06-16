"""Tests for the Redis-backed SSE pub/sub helper.

Uses the autouse `fake_redis` fixture from conftest, which injects an
in-memory FakeRedis as the sse module's client.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import sse


async def _next_message(pubsub, timeout: float = 1.0) -> dict | None:
    """Drain ping/subscribe messages and return the first real payload."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = max(deadline - asyncio.get_event_loop().time(), 0.0)
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
        if msg is None:
            return None
        if msg.get("type") == "message":
            return json.loads(msg["data"])


@pytest.mark.asyncio
async def test_subscribe_receives_published_events():
    async with sse.subscribe("table-1") as pubsub:
        await sse.publish("table-1", {"type": "cell_done", "rowId": "r1"})
        event = await _next_message(pubsub)
        assert event == {"type": "cell_done", "rowId": "r1"}


@pytest.mark.asyncio
async def test_publish_isolated_per_table():
    async with sse.subscribe("table-1") as pubsub_1:
        async with sse.subscribe("table-2") as pubsub_2:
            await sse.publish("table-1", {"type": "a"})
            assert await _next_message(pubsub_1) == {"type": "a"}
            # pubsub_2 should not have received anything
            assert await _next_message(pubsub_2, timeout=0.2) is None


@pytest.mark.asyncio
async def test_publish_to_no_subscribers_is_noop():
    await sse.publish("nobody-home", {"type": "boom"})


@pytest.mark.asyncio
async def test_multiple_subscribers_receive_same_event():
    async with sse.subscribe("table-1") as pubsub_a:
        async with sse.subscribe("table-1") as pubsub_b:
            await sse.publish("table-1", {"type": "ping"})
            assert await _next_message(pubsub_a) == {"type": "ping"}
            assert await _next_message(pubsub_b) == {"type": "ping"}
