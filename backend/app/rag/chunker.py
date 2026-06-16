"""Paragraph-aware character chunking with overlap.

Splits on blank lines first, then assembles paragraphs into chunks that
stay close to a target character count. Maintains overlap from the tail
of the previous chunk to preserve context across boundaries.
"""
from __future__ import annotations

TARGET_CHARS = 800
OVERLAP_CHARS = 150


def chunk_document(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len + 2 > target_chars:
            chunks.append("\n\n".join(current))

            # Carry overlap from the tail of the just-flushed chunk so the
            # next chunk has context.
            overlap: list[str] = []
            overlap_len = 0
            for prev in reversed(current):
                if overlap_len + len(prev) > overlap_chars:
                    break
                overlap.insert(0, prev)
                overlap_len += len(prev) + 2
            current = overlap
            current_len = overlap_len

        current.append(para)
        current_len += para_len + 2

    if current:
        chunks.append("\n\n".join(current))

    return chunks
