"""Celery utilities for robust task execution.

Provides:
- `RobustTask`: Celery `Task` base class with loguru integration, SoftTimeLimit
  catch, idempotent failure-handler hook, and DB connection cleanup.
- `@robust_task`: decorator facade for `@shared_task(bind=True, base=RobustTask, ...)`.
- `STALE_TASK_REGISTRY`: list of (app_label, model_name, ...) entries used by a
  future zombie-task sweeper; empty in Phase 1, populated in Phase 2.
"""

from __future__ import annotations

import time

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from django.db import close_old_connections

from .logging_config import get_logger

logger = get_logger(__name__)

# (app_label, model_name, status_field, running_value, failed_value, error_field, timestamp_field)
STALE_TASK_REGISTRY: list[tuple[str, str, str, str, str, str, str]] = [
    ("gel_analyzer", "DensitometryJob", "status", "RUNNING", "FAILED", "error_message", "started_at"),
]
STALE_TASK_TIMEOUT_HOURS_DEFAULT = 2

_warned_no_time_limit: set[str] = set()


class RobustTask(Task):
    """Celery `Task` base with loguru context, timing, and failure hooks."""

    def __call__(self, *args, **kwargs):
        task_id = self.request.id or "unknown"
        task_name = self.name or self.__class__.__name__
        retries = self.request.retries or 0

        self._failure_handled = False

        if (
            not getattr(self, "soft_time_limit", None)
            and not getattr(self, "time_limit", None)
            and task_name not in _warned_no_time_limit
        ):
            _warned_no_time_limit.add(task_name)
            logger.warning(f"Task {task_name} has no time limit configured — add soft_time_limit/time_limit.")

        bound = logger.bind(task_id=task_id, task_name=task_name, task_retries=retries)
        bound.info(f"=== TASK STARTED === {task_name} args={_safe_repr(args)} kwargs={_safe_repr(kwargs)}")

        start = time.monotonic()
        try:
            result = super().__call__(*args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.info(f"=== TASK COMPLETED === {task_name} elapsed={elapsed_ms:.1f}ms")
            return result
        except SoftTimeLimitExceeded as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.error(f"=== TASK TIMEOUT === {task_name} hit soft time limit after {elapsed_ms:.1f}ms")
            self._do_handle_failure(exc)
            raise
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.exception(f"=== TASK FAILED === {task_name} after {elapsed_ms:.1f}ms")
            self._do_handle_failure(exc)
            raise

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        self._do_handle_failure(exc)
        close_old_connections()

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        close_old_connections()

    def _do_handle_failure(self, exc) -> None:
        if getattr(self, "_failure_handled", False):
            return
        self._failure_handled = True

        model = getattr(self, "_failure_model", None)
        if model is None:
            return

        status_field = getattr(self, "_failure_status_field", "status")
        status_value = getattr(self, "_failure_status_value", "FAILED")
        error_field = getattr(self, "_failure_error_field", None)

        try:
            setattr(model, status_field, status_value)
            if error_field:
                setattr(model, error_field, f"{type(exc).__name__}: {exc}"[:1000])
            update_fields = [status_field] + ([error_field] if error_field else [])
            model.save(update_fields=update_fields)
        except Exception as save_exc:
            logger.warning(f"handle_failure could not update model {model.__class__.__name__}: {save_exc}")


def robust_task(_func=None, **kwargs):
    """Decorator facade for `@shared_task(bind=True, base=RobustTask, ...)`."""
    kwargs["bind"] = True
    kwargs["base"] = RobustTask

    if _func is not None:
        return shared_task(**kwargs)(_func)

    def decorator(func):
        return shared_task(**kwargs)(func)

    return decorator


def _safe_repr(obj, max_len: int = 200) -> str:
    try:
        r = repr(obj)
        return r if len(r) <= max_len else r[:max_len] + "..."
    except Exception:
        return "<unrepresentable>"
