"""Tests for app.rag.search.semantic_search."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from app import models
from app.rag import index as index_module
from app.rag import search as search_module


def _deterministic_embed(texts: list[str]) -> np.ndarray:
    vectors = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        v = np.frombuffer(h[:32], dtype="uint8").astype("float32")[:8] + 1.0
        vectors.append(v)
    arr = np.array(vectors, dtype="float32")
    import faiss
    faiss.normalize_L2(arr)
    return arr


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    async def fake_embed(texts):
        return _deterministic_embed(list(texts))

    # Patch in both modules — index calls embed_texts at build time, search at query time.
    monkeypatch.setattr(index_module, "embed_texts", fake_embed)
    monkeypatch.setattr(search_module, "embed_texts", fake_embed)
    index_module.reset_cache()
    yield
    index_module.reset_cache()


@pytest.mark.asyncio
async def test_semantic_search_returns_hits_for_known_query(session_factory):
    async with session_factory() as db:
        db.add(models.Document(
            arbitrator_id="arb_s",
            doc_type="cv",
            filename="cv.md",
            content="Educated at Yale and Oxford.\n\nSpecializes in commercial arbitration.",
        ))
        await db.commit()

    # Query == exact text of one of the chunks
    hits = await search_module.semantic_search(
        "arb_s",
        "Educated at Yale and Oxford.\n\nSpecializes in commercial arbitration.",
        k=3,
    )
    assert len(hits) >= 1
    assert hits[0]["filename"] == "cv.md"
    assert hits[0]["doc_type"] == "cv"
    assert "Yale" in hits[0]["chunk"]
    assert isinstance(hits[0]["score"], float)


@pytest.mark.asyncio
async def test_semantic_search_returns_empty_when_no_corpus():
    hits = await search_module.semantic_search("arb_missing", "anything", k=5)
    assert hits == []


@pytest.mark.asyncio
async def test_semantic_search_respects_k(session_factory):
    async with session_factory() as db:
        for i in range(8):
            db.add(models.Document(
                arbitrator_id="arb_k",
                doc_type=f"doc_{i}",
                filename=f"doc_{i}.md",
                content=f"Unique content number {i}",
            ))
        await db.commit()

    hits = await search_module.semantic_search("arb_k", "Unique content number 3", k=3)
    assert len(hits) == 3
