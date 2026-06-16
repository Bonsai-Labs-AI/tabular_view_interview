"""Tests for the document seeder.

Specifically verifies idempotency: running the seeder twice over the same
corpus should not create duplicate rows.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app import seed_documents as seed_module
from app.models import Document


def _make_corpus(tmp_path: Path) -> Path:
    """Construct a minimal corpus on disk under tmp_path."""
    root = tmp_path / "documents"
    arb1 = root / "arb_1_vance"
    arb1.mkdir(parents=True)
    (arb1 / "cv.md").write_text("CV body", encoding="utf-8")
    (arb1 / "news_article.md").write_text("News body", encoding="utf-8")

    arb2 = root / "arb_2_torres"
    arb2.mkdir(parents=True)
    (arb2 / "cv.md").write_text("Torres CV", encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_seed_documents_idempotent(session_factory, tmp_path, monkeypatch):
    corpus = _make_corpus(tmp_path)
    monkeypatch.setattr(seed_module, "_CORPUS_ROOT", corpus)

    # Run once
    await seed_module.seed_documents()
    async with session_factory() as db:
        first = (await db.execute(select(Document))).scalars().all()
    assert len(first) == 3
    arb_ids = sorted(d.arbitrator_id for d in first)
    assert arb_ids == ["arb_1", "arb_1", "arb_2"]

    # Run again
    await seed_module.seed_documents()
    async with session_factory() as db:
        second = (await db.execute(select(Document))).scalars().all()

    assert len(second) == 3, "Re-running the seeder must not duplicate rows"


@pytest.mark.asyncio
async def test_seed_documents_missing_corpus(session_factory, tmp_path, monkeypatch):
    """If the corpus directory doesn't exist, seeder returns cleanly."""
    monkeypatch.setattr(seed_module, "_CORPUS_ROOT", tmp_path / "does-not-exist")
    await seed_module.seed_documents()
    # No rows added
    async with session_factory() as db:
        rows = (await db.execute(select(Document))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_seed_documents_skips_non_arb_directories(
    session_factory, tmp_path, monkeypatch
):
    root = tmp_path / "documents"
    root.mkdir(parents=True)
    # Directories that don't match the arb_N pattern should be ignored.
    bogus = root / "junk_dir"
    bogus.mkdir()
    (bogus / "cv.md").write_text("ignored", encoding="utf-8")

    arb = root / "arb_1_vance"
    arb.mkdir()
    (arb / "cv.md").write_text("CV", encoding="utf-8")

    monkeypatch.setattr(seed_module, "_CORPUS_ROOT", root)
    await seed_module.seed_documents()

    async with session_factory() as db:
        rows = (await db.execute(select(Document))).scalars().all()
    assert len(rows) == 1
    assert rows[0].arbitrator_id == "arb_1"
