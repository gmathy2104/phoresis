"""Healthcheck endpoints for Phoresis.

- /healthz/         readiness: DB + Redis + Celery (200 when all ok, 503 if DB or Redis down,
                                                    200 'degraded' if only Celery down)
- /healthz/celery/  worker-only liveness (200 if at least one worker responds, 503 otherwise)

Used by:
- Caddy upstream health-check (Phase 5 docker-compose)
- Watchtower post-update verification (Phase 6)
- /admin/system/ dashboard (post-v1 nice-to-have)
"""

from __future__ import annotations

from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpRequest, JsonResponse


def _db_alive() -> bool:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except OperationalError:
        return False
    except Exception:
        return False


def _redis_alive() -> bool:
    try:
        from django_redis import get_redis_connection

        get_redis_connection("default").ping()
        return True
    except Exception:
        return False


def _celery_alive() -> bool:
    try:
        from phoresis_core.celery_app import app

        # `inspect().ping()` returns a dict {worker_name: {'ok': 'pong'}} per responding worker
        # or None if the broker is unreachable / no workers respond within the timeout.
        result = app.control.inspect(timeout=1).ping()
        return bool(result)
    except Exception:
        return False


def readiness(request: HttpRequest) -> JsonResponse:
    """Composite readiness probe — DB + Redis + Celery."""
    db_ok = _db_alive()
    redis_ok = _redis_alive()
    celery_ok = _celery_alive()

    subsystems = {
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "celery": "ok" if celery_ok else "no workers",
    }

    # Informational, never changes the verdict: the app works without its archive disk, it only cannot
    # re-read archived originals. Present only where an archive is configured (the Mac install).
    from phoresis_core.media_tiers import DISABLED, archive_state

    archive = archive_state()
    if archive.state != DISABLED:
        subsystems["media_archive"] = archive.state

    if not (db_ok and redis_ok):
        overall, status = "error", 503
    elif not celery_ok:
        overall, status = "degraded", 200
    else:
        overall, status = "ok", 200

    return JsonResponse({"overall": overall, "subsystems": subsystems}, status=status)


def celery_only(request: HttpRequest) -> JsonResponse:
    """Cheap worker-only liveness — used by Caddy and the admin dashboard."""
    if _celery_alive():
        return JsonResponse({"status": "ok"}, status=200)
    return JsonResponse({"status": "down"}, status=503)


def liveness(request: HttpRequest) -> JsonResponse:
    """Static liveness probe — process is up, no DB/Redis/Celery touched.

    Used by container orchestrators (Docker `HEALTHCHECK`) to distinguish
    'process alive' from 'fully ready to serve'. Always 200 unless the WSGI
    server itself is wedged (in which case the response never reaches us).
    """
    return JsonResponse({"status": "alive"}, status=200)
