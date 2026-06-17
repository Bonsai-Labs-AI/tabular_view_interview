"""Tests for app.rag.search.semantic_search against a built index."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from app import config as app_config
from app.rag import build as build_module
from app.rag import embeddings as embeddings_module
from app.rag import index as index_module
from app.rag import search as search_module
from app.rag.index import IndexNotBuilt


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
def patch_embeddings_and_paths(tmp_path, monkeypatch):
    async def fake_embed(texts):
        return _deterministic_embed(list(texts))

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed)
    monkeypatch.setattr(build_module, "embed_texts", fake_embed)
    monkeypatch.setattr(search_module, "embed_texts", fake_embed)
    monkeypatch.setattr(app_config.settings, "rag_index_dir", str(tmp_path / "rag_index"))
    monkeypatch.setattr(build_module, "_CORPUS_ROOT", tmp_path / "documents")

    index_module.reset_cache()
    yield
    index_module.reset_cache()


def _seed(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    p = tmp_path / "documents" / name
    p.mkdir(parents=True)
    for fname, content in files.items():
        (p / fname).write_text(content, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_semantic_search_returns_hits(tmp_path):
    _seed(tmp_path, "arb_1_alpha", {
        "cv.md": "Educated at Yale and Oxford.\n\nSpecializes in commercial arbitration.",
    })
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    hits = await search_module.semantic_search(
        "arb_1",
        "Educated at Yale and Oxford.\n\nSpecializes in commercial arbitration.",
        k=3,
    )
    assert len(hits) >= 1
    assert hits[0]["filename"] == "cv.md"
    assert hits[0]["doc_type"] == "cv"
    assert "Yale" in hits[0]["chunk"]
    assert isinstance(hits[0]["score"], float)


@pytest.mark.asyncio
async def test_semantic_search_raises_when_index_missing():
    with pytest.raises(IndexNotBuilt):
        await search_module.semantic_search("arb_missing", "anything", k=5)


@pytest.mark.asyncio
async def test_semantic_search_respects_k(tmp_path):
    files = {f"doc_{i}.md": f"Unique content number {i}" for i in range(8)}
    _seed(tmp_path, "arb_1_alpha", files)
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    hits = await search_module.semantic_search("arb_1", "Unique content number 3", k=3)
    assert len(hits) == 3
