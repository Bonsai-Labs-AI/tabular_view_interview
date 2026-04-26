import asyncio
from typing import Dict, List


_subscribers: Dict[str, List[asyncio.Queue]] = {}


def subscribe(table_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(table_id, []).append(q)
    return q


def unsubscribe(table_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(table_id, [])
    try:
        subs.remove(q)
    except ValueError:
        pass


async def publish(table_id: str, event: dict) -> None:
    for q in list(_subscribers.get(table_id, [])):
        await q.put(event)
