"""Celery application instance configuring task broker, results, and worker routing."""

from celery import Celery

from termnova.config import get_settings

settings = get_settings()

celery_app = Celery(
    "termnova",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["termnova.pipeline.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=900,
    task_soft_time_limit=840,
    result_expires=86400,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.APP_ENV == "test",
    task_routes={
        "termnova.pipeline.tasks.*": {"queue": "ingestion"},
    },
)
