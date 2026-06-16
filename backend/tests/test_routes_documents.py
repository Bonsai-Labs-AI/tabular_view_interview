"""Tests for /documents routes."""
from __future__ import annotations

import pytest

from app.models import Document


async def _seed_documents(session_factory):
    async with session_factory() as db:
        db.add_all([
            Document(
                arbitrator_id="arb_1",
                doc_type="cv",
                filename="cv.md",
                content="CV for Vance",
            ),
            Document(
                arbitrator_id="arb_1",
                doc_type="news_article",
                filename="news_article.md",
                content="News about Vance",
            ),
            Document(
                arbitrator_id="arb_2",
                doc_type="cv",
                filename="cv.md",
                content="CV for Torres",
            ),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_list_documents_for_arbitrator(client, session_factory):
    await _seed_documents(session_factory)

    resp = await client.get("/documents", params={"arbitrator_id": "arb_1"})
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 2
    doc_types = sorted(d["doc_type"] for d in docs)
    assert doc_types == ["cv", "news_article"]
    assert all(d["arbitrator_id"] == "arb_1" for d in docs)


@pytest.mark.asyncio
async def test_list_documents_empty(client, session_factory):
    await _seed_documents(session_factory)
    resp = await client.get("/documents", params={"arbitrator_id": "arb_99"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_documents_missing_arbitrator_id(client):
    resp = await client.get("/documents")
    assert resp.status_code == 422  # FastAPI validation error
