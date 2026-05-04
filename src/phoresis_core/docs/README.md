# `phoresis_core`

Cross-cutting infrastructure shared by every Phoresis app.

## Purpose

Owns:
- Centralized loguru-based logging (`logging_config.py`).
- Celery app instance + `RobustTask` base class + `@robust_task` decorator (`celery_app.py`, `celery_utils.py`).
- Error capture: `ExceptionContextMiddleware`, `ErrorLog` model, error utility helpers (`error_handling/`).
- Navigation registry (`navigation/`) — singleton consumed by sidebar + command palette.
- Healthcheck endpoints (`healthz.py`).
- DRF Spectacular schema view (`api_schema.py`).

This is a *library* app — no user-facing views.

## Public surface

### Logging
- `from phoresis_core.logging_config import get_logger`
- Always use `get_logger(__name__)` (not `logging.getLogger`).

### Celery
- `from phoresis_core.celery_utils import robust_task`
- `@robust_task(soft_time_limit=300, time_limit=360)` — wraps `@shared_task(bind=True, base=RobustTask)`.
- `STALE_TASK_REGISTRY` — populated by gel_analyzer in Phase 2.

### Error handling
- `ExceptionContextMiddleware` — auto-installed in `MIDDLEWARE`.
- `phoresis_core.ErrorLog` — DB-persisted error log; admin lives at `/admin/phoresis_core/errorlog/`.
- `generate_error_id()` returns `PHOR-YYYYMMDD-XXXXXX`.
- Custom 404/500 handlers (`error_handling/views.py`) surface the error_id on the user-facing error page.

### Navigation
- `from phoresis_core.navigation import nav_registry` — register apps in their `nav.py`.
- `autodiscover_nav_modules()` runs in `PhoresisCoreConfig.ready()`.

### Health
- `GET /healthz/` — composite (DB + Redis + Celery).
- `GET /healthz/celery/` — worker-only.
- `GET /healthz/live/` — process liveness (no I/O).

## Key files

| File | Purpose |
|---|---|
| `logging_config.py` | console + file + DB sinks; InterceptHandler |
| `celery_app.py` | Celery instance + autodiscover |
| `celery_utils.py` | RobustTask base + @robust_task |
| `error_handling/middleware.py` | exception capture |
| `error_handling/utils.py` | sanitize_dict, generate_error_id, signature, app-label extraction |
| `error_handling/views.py` | handler404, handler500 |
| `models.py` | ErrorLog |
| `navigation/__init__.py` | NavRegistry singleton |
| `healthz.py` | readiness / celery / liveness |
| `api_schema.py` | DRF Spectacular schema view |

## Integration notes

- `apps.py.ready()` calls `setup_logging()` and `autodiscover_nav_modules()` — apps must be in `INSTALLED_APPS` *after* `phoresis_core` so their `nav.py` modules are discoverable.
- The DB error sink calls `ErrorLog.objects.create(...)` synchronously inside `loguru` — never raise from this code path (silent except).
