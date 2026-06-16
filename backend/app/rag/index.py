"""Per-arbitrator FAISS index built lazily and cached in process.

Each Celery worker process maintains its own cache. First query for a
given arbitrator pays the cost of loading all docs, chunking, embedding,
and adding to FAISS. Subsequent queries hit the in-memory index.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import faiss
import numpy as np
from sqlalchemy import select

from ..database import async_session
from ..models import Document
from .chunker import chunk_document
from .embeddings import EMBEDDING_DIM, embed_texts


@dataclass(frozen=True)
class ChunkMeta:
    arbitrator_id: str
    filename: str
    doc_type: str
    chunk_index: int
    text: str


class ArbitratorIndex:
    """In-memory FAISS index over chunks for a single arbitrator."""

    def __init__(self, chunks: list[ChunkMeta], embeddings: np.ndarray):
        self.chunks = chunks
        if len(chunks) == 0:
            self.index: Optional[faiss.Index] = None
        else:
            self.index = faiss.IndexFlatIP(embeddings.shape[1])
            self.index.add(embeddings)

    def search(self, query_embedding: np.ndarray, k: int) -> list[tuple[ChunkMeta, float]]:
        if self.index is None or len(self.chunks) == 0:
            return []
        k = min(k, len(self.chunks))
        D, I = self.index.search(query_embedding[None, :], k)
        return [
            (self.chunks[i], float(d))
            for i, d in zip(I[0], D[0])
            if i >= 0
        ]


_cache: dict[str, ArbitratorIndex] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(arbitrator_id: str) -> asyncio.Lock:
    if arbitrator_id not in _locks:
        _locks[arbitrator_id] = asyncio.Lock()
    return _locks[arbitrator_id]


async def _load_chunks(arbitrator_id: str) -> tuple[list[ChunkMeta], list[str]]:
    async with async_session() as db:
        result = await db.execute(
            select(Document).where(Document.arbitrator_id == arbitrator_id)
        )
        docs = result.scalars().all()

    chunks: list[ChunkMeta] = []
    texts: list[str] = []
    for doc in docs:
        for i, chunk in enumerate(chunk_document(doc.content)):
            chunks.append(
                ChunkMeta(
                    arbitrator_id=arbitrator_id,
                    filename=doc.filename,
                    doc_type=doc.doc_type,
                    chunk_index=i,
                    text=chunk,
                )
            )
            texts.append(chunk)
    return chunks, texts


async def get_index(arbitrator_id: str) -> ArbitratorIndex:
    if arbitrator_id in _cache:
        return _cache[arbitrator_id]

    async with _lock_for(arbitrator_id):
        if arbitrator_id in _cache:
            return _cache[arbitrator_id]

        chunks, texts = await _load_chunks(arbitrator_id)
        if not texts:
            empty = ArbitratorIndex([], np.zeros((0, EMBEDDING_DIM), dtype="float32"))
            _cache[arbitrator_id] = empty
            return empty

        embeddings = await embed_texts(texts)
        idx = ArbitratorIndex(chunks, embeddings)
        _cache[arbitrator_id] = idx
        return idx


def reset_cache() -> None:
    """Drop all cached indexes. Tests use this between cases."""
    _cache.clear()
    _locks.clear()
