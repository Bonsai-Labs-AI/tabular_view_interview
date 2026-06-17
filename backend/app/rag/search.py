"""Top-level semantic-search entry point used by the doc subagent."""
from __future__ import annotations

from .embeddings import embed_texts
from .index import IndexNotBuilt, load_index


async def semantic_search(arbitrator_id: str, query: str, k: int = 5) -> list[dict]:
    """Return the top-k chunks across the arbitrator's documents.

    Each result is a dict with `filename`, `doc_type`, `chunk`, `score`.
    Scores are inner-product values on L2-normalized vectors, i.e. cosine
    similarities in [-1, 1] (typically 0.2-0.7 for relevant matches).

    Raises `IndexNotBuilt` if the RAG index for this arbitrator has not
    been built — the operator must run the offline pipeline first.
    """
    index = load_index(arbitrator_id)
    if not index.chunks:
        return []

    query_emb = await embed_texts([query])
    hits = index.search(query_emb[0], k)
    return [
        {
            "filename": meta.filename,
            "doc_type": meta.doc_type,
            "chunk": meta.text,
            "score": score,
        }
        for meta, score in hits
    ]
