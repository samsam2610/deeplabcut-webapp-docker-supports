"""Celery application for the dlc-3d lightning-pose worker.

Separate from the main webapp's Celery instance. Consumes the 'lp_3d' queue.
"""
import os
from celery import Celery

celery = Celery(
    "dlc_3d_lp",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
    include=["dlc_3d_bp.lp.tasks"],
)

celery.conf.update(
    task_default_queue="lp_3d",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 86400},
    result_extended=True,
)
