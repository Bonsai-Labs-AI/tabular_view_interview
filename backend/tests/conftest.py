"""Shared test fixtures.

Provides:
- An isolated in-memory SQLite engine + session factory per test
- Monkeypatches `app.database.async_session` (and modules that imported it) so
  application code runs against the in-memory DB
- A FastAPI `httpx.AsyncClient` bound to the app
- Helpers + fixtures to monkeypatch OpenAI `AsyncOpenAI.chat.completions.create`
  with scripted tool-call responses
- A fixture that monkeypatches `tavily.TavilyClient.search` with deterministic
  results
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Make the backend package importable when running `pytest` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app import database as app_database  # noqa: E402
from app import orchestrator as orchestrator_module  # noqa: E402
from app import seed_documents as seed_documents_module  # noqa: E402
from app import sse as app_sse  # noqa: E402
from app.database import Base  # noqa: E402
from app.routes import tables as tables_route  # noqa: E402
from app.workers import cell_worker  # noqa: E402


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine per test.

    We use a single shared connection by setting poolclass=StaticPool so the
    in-memory database persists across async sessions during the test.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Ensure all models are registered before creating tables.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def patch_async_session(session_factory, monkeypatch):
    """Patch `async_session` everywhere it's used so app code hits the test DB.

    We patch the symbol in every module that did `from ..database import async_session`
    because they hold their own reference.
    """
    monkeypatch.setattr(app_database, "async_session", session_factory, raising=True)
    monkeypatch.setattr(cell_worker, "async_session", session_factory, raising=True)
    monkeypatch.setattr(seed_documents_module, "async_session", session_factory, raising=True)

    # `get_db` also uses async_session inside app.database, so patching there is
    # enough for routes that use `Depends(get_db)`. But routes/tables.py imported
    # the symbol directly too — check and patch if present.
    if hasattr(tables_route, "async_session"):
        monkeypatch.setattr(tables_route, "async_session", session_factory, raising=True)

    yield


@pytest_asyncio.fixture(autouse=True)
async def fake_redis(monkeypatch):
    """Inject a per-test fakeredis client into the SSE module.

    Each test gets its own in-memory Redis-equivalent so publish/subscribe
    state doesn't leak between cases.
    """
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(app_sse, "_client", client)
    monkeypatch.setattr(app_sse, "get_redis", lambda: client)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def patch_orchestrator_dispatch(monkeypatch):
    """Replace orchestrator.enqueue_cell with an inline fill_cell call.

    Real production path: orchestrator.enqueue_cell -> Celery -> worker
    process -> asyncio.run(fill_cell(cell_id)). For tests we collapse that to
    `asyncio.create_task(fill_cell(cell_id))` so the agent loop runs in the
    test's event loop. Tests that want to stub the worker further can patch
    `app.orchestrator.enqueue_cell` directly.
    """
    import asyncio as _asyncio

    def inline_enqueue(cell_id: str) -> None:
        _asyncio.create_task(cell_worker.fill_cell(cell_id))

    monkeypatch.setattr(orchestrator_module, "enqueue_cell", inline_enqueue)
    yield


# ---------------------------------------------------------------------------
# FastAPI client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(patch_async_session):
    """An httpx AsyncClient bound to the FastAPI app.

    Uses ASGITransport so we skip uvicorn entirely. Also skips the lifespan
    handler so we don't trigger `init_db()` against a real file DB — the
    in-memory schema is already created by the `engine` fixture.
    """
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# OpenAI mocking
# ---------------------------------------------------------------------------


def make_tool_call(name: str, arguments: dict | str, call_id: str = "call_1") -> Any:
    """Build a fake OpenAI tool_call object.

    The real SDK returns objects with attribute access; we mimic that with
    SimpleNamespace so that `tc.id`, `tc.function.name`, and
    `tc.function.arguments` all work.
    """
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_response(
    *,
    tool_calls: Iterable[Any] | None = None,
    content: str | None = None,
) -> Any:
    """Build a fake `chat.completions.create` response."""
    message = SimpleNamespace(
        role="assistant",
        content=content,
        tool_calls=list(tool_calls) if tool_calls else None,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_planner_response(text: str = "Search the web and read the CV.") -> Any:
    return make_response(content=text)


def make_submit_findings_response(summary: str = "summary", sources: list | None = None) -> Any:
    sources = sources or [{"title": "T", "url": "https://example.com"}]
    return make_response(
        tool_calls=[make_tool_call("submit_findings", {"summary": summary, "sources": sources})]
    )


def make_submit_answer_response(
    answer: str = "the answer",
    confidence: str = "high",
    reasoning: str = "because reasons",
    sources: list | None = None,
) -> Any:
    sources = sources or [{"title": "T", "url": "https://example.com"}]
    return make_response(
        tool_calls=[
            make_tool_call(
                "submit_answer",
                {
                    "answer": answer,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "sources": sources,
                },
            )
        ]
    )


class _ScriptedOpenAI:
    """Drop-in fake for AsyncOpenAI whose .chat.completions.create returns the
    next response from a scripted queue.

    Usage:
        fake = _ScriptedOpenAI([resp1, resp2, ...])
        # or with a callable:
        fake = _ScriptedOpenAI(handler=lambda **kw: response_for_call(kw))
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        handler: Callable[..., Any] | None = None,
    ):
        self._responses = list(responses) if responses else []
        self._handler = handler
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def __call__(self, *args, **kwargs):  # so `AsyncOpenAI(api_key=...)` returns self
        return self

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._handler is not None:
            return self._handler(**kwargs)
        if not self._responses:
            raise AssertionError("No more scripted OpenAI responses queued")
        return self._responses.pop(0)


@pytest.fixture
def scripted_openai_factory(monkeypatch):
    """Return a factory that installs a scripted AsyncOpenAI everywhere needed.

    Returns the `_ScriptedOpenAI` so tests can inspect `.calls`.
    """

    def install(
        responses: list[Any] | None = None,
        *,
        handler: Callable[..., Any] | None = None,
    ) -> _ScriptedOpenAI:
        fake = _ScriptedOpenAI(responses, handler=handler)
        # Patch AsyncOpenAI in the modules that imported it directly.
        monkeypatch.setattr(cell_worker, "AsyncOpenAI", fake, raising=True)
        monkeypatch.setattr(tables_route, "AsyncOpenAI", fake, raising=True)
        return fake

    return install


# ---------------------------------------------------------------------------
# Tavily mocking
# ---------------------------------------------------------------------------


class _FakeTavily:
    def __init__(self, results: list[dict] | None = None, *, raise_exc: Exception | None = None):
        self.results = results if results is not None else [
            {"title": "Example", "url": "https://example.com", "content": "Body"}
        ]
        self.raise_exc = raise_exc
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):  # `TavilyClient(api_key=...)` returns self
        return self

    def search(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"results": self.results}


@pytest.fixture
def patch_tavily(monkeypatch):
    """Replace `tavily.TavilyClient` with a deterministic fake.

    Returns the fake so tests can inspect .calls or reconfigure .results.
    """
    fake = _FakeTavily()

    import tavily

    monkeypatch.setattr(tavily, "TavilyClient", fake, raising=True)
    return fake
