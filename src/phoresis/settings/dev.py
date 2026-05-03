"""Development settings — local Postgres, DEBUG=True."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "phoresis"]

# Phase 1: keep manifest storage off in dev to avoid collectstatic friction
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]
