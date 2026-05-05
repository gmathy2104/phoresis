"""Centralised loguru configuration for Phoresis.

Provides:
- Console sink (always on, colourised in DEBUG)
- File sinks (only in DEBUG, rotated daily, 30-day retention)
- DB error sink — writes ERROR+ records to phoresis_core.ErrorLog
- InterceptHandler — bridges stdlib `logging` to loguru
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from loguru import logger

from django.conf import settings

CONSOLE_FORMAT_DEV = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

CONSOLE_FORMAT_PROD = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[name]} | {message}"
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[name]}:{function}:{line} | {message}"


class InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).bind(name=record.name).log(level, record.getMessage())


def db_error_sink(message) -> None:
    """Persist ERROR+ records to `phoresis_core.ErrorLog`."""
    from django.utils.timezone import now

    from phoresis_core.error_handling.utils import extract_app_label
    from phoresis_core.models import ErrorLog

    record = message.record

    ignored_loggers = {"django.request", "django.server", "django.security", "celery.app.trace"}
    logger_name = record.get("extra", {}).get("name", "")
    if logger_name in ignored_loggers:
        return

    try:
        exception_type = None
        exception_text = None
        if record["exception"]:
            exception_type = record["exception"].type.__name__
            exception_text = "".join(
                traceback.format_exception(
                    record["exception"].type, record["exception"].value, record["exception"].traceback
                )
            )

        extra = record.get("extra", {})
        file_path = str(record["file"].path) if record["file"] else None
        source_type = extra.get("source_type") or ErrorLog.SOURCE_TYPE_OTHER
        app_label = extra.get("app_label") or extract_app_label(file_path)

        ErrorLog.objects.create(
            timestamp=now(),
            level=record["level"].name,
            message=str(record["message"]),
            pathname=file_path,
            func_name=record["function"],
            lineno=record["line"],
            exception_type=exception_type,
            exception_text=exception_text,
            user=extra.get("user"),
            request_path=extra.get("request_path"),
            error_id=extra.get("error_id"),
            http_method=extra.get("http_method"),
            user_agent=extra.get("user_agent"),
            referer=extra.get("referer"),
            client_ip=extra.get("client_ip"),
            view_name=extra.get("view_name"),
            view_func_name=extra.get("view_func_name"),
            request_data=extra.get("request_data"),
            error_signature=extra.get("error_signature"),
            is_handled=extra.get("is_handled", False),
            source_type=source_type,
            app_label=app_label,
            task_name=extra.get("task_name"),
            task_id=extra.get("task_id"),
            queue_name=extra.get("queue_name"),
            retry_count=extra.get("retry_count"),
            hostname=extra.get("hostname"),
            task_args=extra.get("task_args"),
            task_kwargs=extra.get("task_kwargs"),
        )
    except Exception:
        # Never raise from a log sink — would create an infinite error loop.
        pass


_logging_configured = False


def setup_logging() -> None:
    """Configure loguru — safe to call multiple times (idempotent)."""
    global _logging_configured
    if _logging_configured:
        return

    logger.remove()

    debug_mode = bool(getattr(settings, "DEBUG", False))
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))

    logger.add(
        sys.stdout,
        format=CONSOLE_FORMAT_DEV if debug_mode else CONSOLE_FORMAT_PROD,
        level="DEBUG" if debug_mode else "INFO",
        colorize=True,
        backtrace=debug_mode,
        diagnose=debug_mode,
        filter=lambda r: r["extra"].setdefault("name", "root") or True,
    )

    if debug_mode:
        # Env-overridable per AGENTS.md §5 (writable path policy). Required for
        # the dev-stack worker container, where the default `BASE_DIR / "logs"`
        # would resolve to /app/logs — which is root-owned because Dockerfile's
        # `WORKDIR /app` runs before the user is changed to phoresis (UID 1000).
        # Outside containers, BASE_DIR/logs is fine and stays the default.
        log_dir = Path(os.environ.get("PHORESIS_LOG_DIR") or (base_dir / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "phoresis_{time:YYYY-MM-DD}.log",
            format=FILE_FORMAT,
            level="INFO",
            rotation="00:00",
            retention="30 days",
            compression="gz",
            enqueue=False,
            filter=lambda r: r["extra"].setdefault("name", "root") or True,
        )
        logger.add(
            log_dir / "errors_{time:YYYY-MM-DD}.log",
            format=FILE_FORMAT,
            level="ERROR",
            rotation="00:00",
            retention="90 days",
            compression="gz",
            enqueue=False,
            filter=lambda r: r["extra"].setdefault("name", "root") or True,
        )

    logger.add(db_error_sink, level="ERROR", enqueue=False)

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in (
        "django",
        "django.request",
        "django.db.backends",
        "django.security",
        "celery",
        "celery.task",
        "celery.worker",
    ):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [InterceptHandler()]
        std_logger.propagate = False

    _logging_configured = True
    logger.bind(name="phoresis_core.logging_config").info("Loguru configured")


def get_logger(name: str | None = None):
    """Return a loguru logger bound with `name` (typically `__name__`)."""
    return logger.bind(name=name or "root")


__all__ = ("get_logger", "setup_logging", "logger", "InterceptHandler")
