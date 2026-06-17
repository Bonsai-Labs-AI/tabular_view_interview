"""Tests for the disk-based RAG index: build pipeline + load + search + cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app import config as app_config
from app.rag import build as build_module
from app.rag import embeddings as embeddings_module
from app.rag import index as index_module
from app.rag.index import IndexNotBuilt, load_index


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
    """Point the index dir at a tmp_path and stub OpenAI embeddings."""
    async def fake_embed(texts):
        return _deterministic_embed(list(texts))

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed)
    monkeypatch.setattr(build_module, "embed_texts", fake_embed)

    # Redirect the index_dir to tmp.
    monkeypatch.setattr(app_config.settings, "rag_index_dir", str(tmp_path / "rag_index"))

    # Redirect the corpus root to tmp too, so build sees the test fixtures.
    monkeypatch.setattr(build_module, "_CORPUS_ROOT", tmp_path / "documents")

    index_module.reset_cache()
    yield
    index_module.reset_cache()


def _seed_corpus(tmp_path: Path, arb_dir_name: str, files: dict[str, str]) -> Path:
    arb_dir = tmp_path / "documents" / arb_dir_name
    arb_dir.mkdir(parents=True)
    for fname, content in files.items():
        (arb_dir / fname).write_text(content, encoding="utf-8")
    return arb_dir


@pytest.mark.asyncio
async def test_build_writes_index_chunks_and_manifest(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {
        "cv.md": "Educated at Yale.\n\nSpecialty in commercial arbitration.",
        "news.md": "Appointed chair of a tribunal in 2024.",
    })

    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    out_dir = Path(app_config.settings.rag_index_dir) / "arb_1"
    assert (out_dir / "index.faiss").exists()
    assert (out_dir / "chunks.jsonl").exists()
    assert (out_dir / "manifest.json").exists()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["arbitrator_id"] == "arb_1"
    assert manifest["num_chunks"] >= 2
    assert manifest["num_documents"] == 2
    assert "built_at" in manifest


@pytest.mark.asyncio
async def test_build_skip_when_manifest_exists(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {"cv.md": "content"})
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)
    manifest_path = Path(app_config.settings.rag_index_dir) / "arb_1" / "manifest.json"
    first_mtime = manifest_path.stat().st_mtime

    # Re-run without --force; should be a no-op (skip).
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)
    assert manifest_path.stat().st_mtime == first_mtime


@pytest.mark.asyncio
async def test_build_force_rebuilds(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {"cv.md": "original content"})
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    # Modify corpus and rebuild with force.
    (tmp_path / "documents" / "arb_1_alpha" / "cv.md").write_text("new content")
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=True)

    out_dir = Path(app_config.settings.rag_index_dir) / "arb_1"
    chunks = [json.loads(l) for l in (out_dir / "chunks.jsonl").read_text().splitlines()]
    assert any("new content" in c["text"] for c in chunks)


@pytest.mark.asyncio
async def test_load_index_then_search(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {
        "doc1.md": "The cat sat on the mat.",
        "doc2.md": "Hello world, this is a test document.",
        "doc3.md": "A completely unrelated chunk about astronomy.",
    })
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    idx = load_index("arb_1")
    assert idx.arbitrator_id == "arb_1"
    assert len(idx.chunks) == 3

    # Query that should top out as the "astronomy" chunk
    target = next(c for c in idx.chunks if "astronomy" in c.text)
    q_emb = _deterministic_embed([target.text])[0]
    hits = idx.search(q_emb, k=3)
    assert len(hits) == 3
    assert hits[0][0].text == target.text
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_load_index_missing_raises(tmp_path):
    with pytest.raises(IndexNotBuilt):
        load_index("arb_99")


@pytest.mark.asyncio
async def test_load_index_caches_in_process(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {"cv.md": "content"})
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    a = load_index("arb_1")
    b = load_index("arb_1")
    assert a is b


@pytest.mark.asyncio
async def test_reset_cache_drops_loaded_index(tmp_path):
    _seed_corpus(tmp_path, "arb_1_alpha", {"cv.md": "content"})
    await build_module.build_index_for("arb_1", tmp_path / "documents" / "arb_1_alpha", force=False)

    a = load_index("arb_1")
    index_module.reset_cache()
    b = load_index("arb_1")
    assert a is not b


@pytest.mark.asyncio
async def test_build_main_walks_corpus_root(tmp_path):
    """`build.main` discovers all arb_* subdirs under _CORPUS_ROOT."""
    _seed_corpus(tmp_path, "arb_1_alpha", {"cv.md": "alpha"})
    _seed_corpus(tmp_path, "arb_2_beta", {"cv.md": "beta"})
    (tmp_path / "documents" / "not_an_arb").mkdir()

    import argparse
    args = argparse.Namespace(arbitrator=None, force=False)
    await build_module.main(args)

    index_root = Path(app_config.settings.rag_index_dir)
    assert (index_root / "arb_1" / "manifest.json").exists()
    assert (index_root / "arb_2" / "manifest.json").exists()
    assert not (index_root / "not_an_arb").exists()
