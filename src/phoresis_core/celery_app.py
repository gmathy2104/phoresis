"""Celery application entry point — instantiated at Django startup."""

import os

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")

app = Celery("phoresis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@celery_setup_logging.connect
def configure_celery_logging(**_kwargs) -> None:
    """Route Celery's own logging through loguru, not the stdlib root logger."""
    from phoresis_core.logging_config import setup_logging

    setup_logging()


@worker_ready.connect
def trigger_boot_orphan_purge(sender, **_kwargs) -> None:
    """
    Run the orphan-GelImage purge once on worker startup so a freshly
    booted container doesn't have to wait until 03:30 (the periodic
    schedule) to clear orphans accumulated while the worker was down.

    Only fires from a worker that consumes the `default` queue, so the
    `heavy`-only worker (band detection / SAM) doesn't kick a duplicate
    sweep. ``countdown=30`` lets migrations and the broker handshake
    settle before we touch the DB.
    """
    queues = {q.name for q in (sender.app.amqp.queues.consume_from or [])} if sender else set()
    if queues and "default" not in queues:
        return
    try:
        from gel_analyzer.tasks import purge_orphan_gel_images

        purge_orphan_gel_images.apply_async(countdown=30, queue="default")
    except Exception as exc:
        from phoresis_core.logging_config import get_logger

        get_logger(__name__).warning(f"Boot-time orphan purge failed to enqueue: {exc}")


@app.task(bind=True)
def debug_task(self) -> None:
    """Smoke-test task — `from phoresis_core.celery_app import debug_task; debug_task.delay()`."""
    from phoresis_core.logging_config import get_logger

    get_logger("celery.debug").info(f"Request: {self.request!r}")
