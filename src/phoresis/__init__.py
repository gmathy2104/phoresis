"""Phoresis Django project — re-exports the Celery app for autodiscovery."""

from phoresis_core.celery_app import app as celery_app

__all__ = ("celery_app",)
