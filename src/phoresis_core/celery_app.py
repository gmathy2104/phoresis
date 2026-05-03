"""Celery application entry point — instantiated at Django startup."""

import os

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")

app = Celery("phoresis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@celery_setup_logging.connect
def configure_celery_logging(**_kwargs) -> None:
    """Route Celery's own logging through loguru, not the stdlib root logger."""
    from phoresis_core.logging_config import setup_logging

    setup_logging()


@app.task(bind=True)
def debug_task(self) -> None:
    """Smoke-test task — `from phoresis_core.celery_app import debug_task; debug_task.delay()`."""
    from phoresis_core.logging_config import get_logger

    get_logger("celery.debug").info(f"Request: {self.request!r}")
