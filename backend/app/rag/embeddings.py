"""OpenAI embeddings for the RAG layer.

Uses text-embedding-3-small (1536-d). Returns L2-normalized arrays so
inner-product search behaves like cosine similarity.
"""
from __future__ import annotations

import faiss
import numpy as np
from openai import AsyncOpenAI

from ..config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


async def embed_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype="float32")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    arr = np.array([d.embedding for d in response.data], dtype="float32")
    faiss.normalize_L2(arr)
    return arr
