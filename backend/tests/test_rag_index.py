"""Tests for app.rag.index — FAISS index build, search, cache."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from app import models
from app.rag import index as index_module


def _deterministic_embed(texts: list[str]) -> np.ndarray:
    """A small, deterministic stand-in for OpenAI embeddings.

    Hash each text to seed an 8-d vector. Tests only need stable, distinct
    vectors that L2-normalize; semantic meaningfulness doesn't matter.
    """
    vectors = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        # 8 floats from the first 32 bytes of the hash
        v = np.frombuffer(h[:32], dtype="uint8").astype("float32")[:8]
        # add a tiny constant so vectors aren't degenerate
        v = v + 1.0
        vectors.append(v)
    arr = np.array(vectors, dtype="float32")
    # Normalize so inner-product == cosine
    import faiss
    faiss.normalize_L2(arr)
    return arr


@pytest.fixture(autouse=True)
def patch_embeddings_and_reset_cache(monkeypatch):
    async def fake_embed(texts):
        return _deterministic_embed(list(texts))

    monkeypatch.setattr(index_module, "embed_texts", fake_embed)
    index_module.reset_cache()
    yield
    index_module.reset_cache()


async def _seed_docs(session_factory, arbitrator_id: str, files: dict[str, str]):
    async with session_factory() as db:
        for filename, content in files.items():
            doc_type = filename.rsplit(".", 1)[0]
            db.add(
                models.Document(
                    arbitrator_id=arbitrator_id,
                    doc_type=doc_type,
                    filename=filename,
                    content=content,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_get_index_builds_from_documents(session_factory):
    await _seed_docs(
        session_factory,
        "arb_test",
        {
            "cv.md": "Education at Yale.\n\nSpecialty in commercial arbitration.",
            "news.md": "Appointed chair of a tribunal in 2024.",
        },
    )
    idx = await index_module.get_index("arb_test")

    assert len(idx.chunks) >= 2
    assert all(c.arbitrator_id == "arb_test" for c in idx.chunks)
    filenames = {c.filename for c in idx.chunks}
    assert filenames == {"cv.md", "news.md"}


@pytest.mark.asyncio
async def test_get_index_returns_empty_for_no_docs():
    idx = await index_module.get_index("arb_unknown")
    assert idx.chunks == []
    assert idx.search(np.zeros(8, dtype="float32"), k=5) == []


@pytest.mark.asyncio
async def test_get_index_caches_per_arbitrator(session_factory):
    await _seed_docs(session_factory, "arb_a", {"cv.md": "First arb"})
    idx_1 = await index_module.get_index("arb_a")
    idx_2 = await index_module.get_index("arb_a")
    assert idx_1 is idx_2  # cached identity


@pytest.mark.asyncio
async def test_search_top_k_ordering(session_factory):
    await _seed_docs(
        session_factory,
        "arb_q",
        {
            "doc1.md": "The cat sat on the mat.",
            "doc2.md": "Hello world, this is a test document.",
            "doc3.md": "A completely unrelated chunk about astronomy.",
        },
    )
    idx = await index_module.get_index("arb_q")

    # Query embedding == one of the existing chunk embeddings -> that chunk
    # should be the top result.
    target_chunk = next(c for c in idx.chunks if "astronomy" in c.text)
    query_emb = _deterministic_embed([target_chunk.text])[0]

    hits = idx.search(query_emb, k=3)
    assert len(hits) == 3
    assert hits[0][0].text == target_chunk.text
    # Scores monotonically non-increasing
    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_reset_cache_drops_built_indexes(session_factory):
    await _seed_docs(session_factory, "arb_r", {"cv.md": "content"})
    idx_1 = await index_module.get_index("arb_r")
    index_module.reset_cache()
    idx_2 = await index_module.get_index("arb_r")
    assert idx_1 is not idx_2  # rebuilt
