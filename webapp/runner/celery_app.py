"""Celery configuration for the PPT Master job runner."""

from celery import Celery

from api.config import get_settings

settings = get_settings()
celery_app = Celery("pptmaster_runner", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_default_queue="pptmaster-jobs",
    task_time_limit=settings.celery_task_time_limit,
    task_track_started=True,
    # Template imports run agent-assisted work and would otherwise hold the
    # single-concurrency generation queue for minutes at a time. Material
    # extraction (anydoc + OCR) gets its own queue for the same reason.
    task_routes={
        "runner.import_template": {"queue": "pptmaster-template-imports"},
        "runner.extract_material": {"queue": "pptmaster-documents"},
    },
)
celery_app.autodiscover_tasks(["runner"])
