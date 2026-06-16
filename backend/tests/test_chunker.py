"""Tests for app.rag.chunker."""
from __future__ import annotations

from app.rag.chunker import chunk_document


def test_short_text_returns_single_chunk():
    text = "One short paragraph."
    assert chunk_document(text) == ["One short paragraph."]


def test_empty_text_returns_no_chunks():
    assert chunk_document("") == []
    assert chunk_document("\n\n\n") == []


def test_multiple_short_paragraphs_pack_into_one_chunk():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_document(text, target_chars=200, overlap_chars=20)
    assert len(chunks) == 1
    assert "First" in chunks[0]
    assert "Third" in chunks[0]


def test_long_text_splits_at_paragraph_boundaries():
    paragraphs = [f"Paragraph number {i} with enough text to matter." for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_document(text, target_chars=200, overlap_chars=40)
    assert len(chunks) > 1
    # Every chunk should end at a paragraph boundary (i.e. no chunk ends mid-word).
    for c in chunks:
        assert not c.endswith(" ")


def test_chunks_carry_overlap_from_previous():
    paragraphs = [f"Paragraph {i:02d} of medium length, around forty characters." for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_document(text, target_chars=200, overlap_chars=60)
    assert len(chunks) >= 2
    # The last paragraph of chunk[0] should appear at the start of chunk[1].
    last_para_of_first = chunks[0].split("\n\n")[-1]
    assert last_para_of_first in chunks[1]


def test_no_overlap_when_overlap_chars_zero():
    paragraphs = [f"Para {i}." * 10 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_document(text, target_chars=200, overlap_chars=0)
    assert len(chunks) >= 2
    # No paragraph from chunk[0] should reappear in chunk[1].
    first_paras = set(chunks[0].split("\n\n"))
    second_paras = set(chunks[1].split("\n\n"))
    assert first_paras.isdisjoint(second_paras)
