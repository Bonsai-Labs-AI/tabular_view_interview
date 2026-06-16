"""Retrieval-augmented generation utilities.

Built around FAISS for per-arbitrator vector search over chunked documents.
Each Celery worker process maintains an in-memory cache of arbitrator
indexes built lazily on first query.
"""
