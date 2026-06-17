"""Per-arbitrator FAISS index loaded from disk.

Indexes are built offline by `app.rag.build` and persisted under
<rag_index_dir>/<arbitrator_id>/. At query time we load index.faiss +
chunks.jsonl, then cache in memory per worker process for subsequent
calls.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

from ..config import settings


@dataclass(frozen=True)
class ChunkMeta:
    arbitrator_id: str
    filename: str
    doc_type: str
    chunk_index: int
    text: str


class IndexNotBuilt(RuntimeError):
    """Raised when a query hits an arbitrator whose index has not been built."""


class ArbitratorIndex:
    """A FAISS index plus parallel chunk metadata for a single arbitrator."""

    def __init__(
        self,
        arbitrator_id: str,
        chunks: list[ChunkMeta],
        index: Optional[faiss.Index],
    ):
        self.arbitrator_id = arbitrator_id
        self.chunks = chunks
        self.index = index

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
_cache_lock = threading.Lock()


def _index_dir(arbitrator_id: str) -> Path:
    return Path(settings.rag_index_dir) / arbitrator_id


def load_index(arbitrator_id: str) -> ArbitratorIndex:
    """Load a built index from disk; cached in process for subsequent calls.

    Raises IndexNotBuilt if no manifest exists for this arbitrator — the
    operator must run `python -m app.rag.build` first.
    """
    if arbitrator_id in _cache:
        return _cache[arbitrator_id]

    with _cache_lock:
        if arbitrator_id in _cache:
            return _cache[arbitrator_id]

        d = _index_dir(arbitrator_id)
        manifest_path = d / "manifest.json"
        index_path = d / "index.faiss"
        chunks_path = d / "chunks.jsonl"

        if not manifest_path.exists():
            raise IndexNotBuilt(
                f"No RAG index found for {arbitrator_id} at {d}. "
                "Run `python -m app.rag.build` to build it."
            )

        faiss_index = faiss.read_index(str(index_path))
        chunks: list[ChunkMeta] = []
        with chunks_path.open(encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                chunks.append(ChunkMeta(
                    arbitrator_id=arbitrator_id,
                    filename=obj["filename"],
                    doc_type=obj["doc_type"],
                    chunk_index=obj["chunk_index"],
                    text=obj["text"],
                ))

        arb_idx = ArbitratorIndex(arbitrator_id, chunks, faiss_index)
        _cache[arbitrator_id] = arb_idx
        return arb_idx


def reset_cache() -> None:
    """Drop all cached indexes. Tests use this between cases."""
    _cache.clear()
