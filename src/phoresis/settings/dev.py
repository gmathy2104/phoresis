"""Development settings — local Postgres, DEBUG=True."""

import os
from pathlib import Path

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "phoresis"]

# ── Database — protect the native dev session from polluted DB_* ──────
# base.py wires DATABASES["default"] to DB_HOST / DB_USER / DB_PASSWORD /
# DB_NAME from os.environ. That's perfect when settings.dev is loaded
# *inside a container* (docker/compose.dev.yml injects DB_HOST=
# host.docker.internal et al. from the stack's --env-file) — but a
# footgun on the bare-metal dev host when unrelated DB_* vars are set at
# the OS user level for a sibling project (e.g. Azure Postgres). Those
# vars silently hijack `manage.py runserver` → connection timeout
# against the wrong host.
#
# Decision rule:
#   - In Docker (file /.dockerenv exists): trust DB_* injected by the
#     compose stack — the container has its own clean env.
#   - On bare metal: ignore DB_*, pin to the native local Postgres.
#     PHORESIS_DB_* is the override escape-hatch (won't collide with
#     any other project's DB_* vars).
#
# Docker prod is unaffected either way — it loads settings.prod.
_IN_DOCKER = Path("/.dockerenv").exists()

if not _IN_DOCKER:
    DATABASES["default"]["HOST"] = os.environ.get("PHORESIS_DB_HOST", "127.0.0.1")
    DATABASES["default"]["PORT"] = os.environ.get("PHORESIS_DB_PORT", "5432")
    # Default to phoresis_dev so the bare-metal runserver never accidentally
    # mutates the same database the Docker prod stack reads/writes
    # (host.docker.internal:5432, NAME=phoresis). Both DBs live on the same
    # native Postgres instance, but are otherwise isolated.
    DATABASES["default"]["NAME"] = os.environ.get("PHORESIS_DB_NAME", "phoresis_dev")
    DATABASES["default"]["USER"] = os.environ.get("PHORESIS_DB_USER", "phoresis")
    DATABASES["default"]["PASSWORD"] = os.environ.get("PHORESIS_DB_PASSWORD", "phoresis")

    # ── Redis broker / cache — point at the devstack on bare metal ────
    # base.py wires REDIS_HOST=127.0.0.1, REDIS_PORT=6379. On the dev
    # Windows host that port is typically NOT a phoresis Redis (the prod
    # stack's redis is internal-only, the dev host may have a sibling
    # project's redis like dshub-dev-redis bound to 6379) — so tasks
    # enqueued by `runserver` end up in the wrong broker, no phoresis
    # worker consumes them, and the frontend polls /api/tasks/<id>/status/
    # forever showing PENDING.
    #
    # The Phoresis devstack (compose.devstack.yml) maps its Redis on
    # host port 16379 specifically to avoid that collision. Default the
    # bare-metal dev session there, with PHORESIS_REDIS_* as the override
    # escape-hatch for unusual setups (eager-mode tests, alternative
    # broker, etc.).
    REDIS_HOST = os.environ.get("PHORESIS_REDIS_HOST", "127.0.0.1")
    REDIS_PORT = os.environ.get("PHORESIS_REDIS_PORT", "16379")
    _REDIS_BASE = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    CELERY_BROKER_URL = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
    CELERY_RESULT_BACKEND = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
    CACHES["default"]["LOCATION"] = f"{_REDIS_BASE}/{REDIS_DB_CACHE}"

# Phase 1: keep manifest storage off in dev to avoid collectstatic friction.
# Reconstruct STORAGES (rather than mutating the dict imported from base) so that
# importing both dev and another settings module in the same process can't
# corrupt the staticfiles backend reference.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

INTERNAL_IPS = ["127.0.0.1"]

# Print emails to the runserver console rather than trying to deliver via SMTP.
# Without this, any code path that calls send_mail() (password reset flow, our
# error notifications, etc.) blocks for ~30s on a connection to localhost:25
# and ultimately fails — annoying in dev and a real footgun if the message is
# triggered from inside a web request (the user just sees a hung page).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
