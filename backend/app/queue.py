"""Celery application — broker is Redis, no result backend (workers write
results back to the DB directly).
"""
from __future__ import annotations

from celery import Celery

from .config import settings

celery_app = Celery(
    "arbitrator",
    broker=settings.celery_broker_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="cells",
    broker_connection_retry_on_startup=True,
)
