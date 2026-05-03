"""Tests for phoresis_core.logging_config."""

from phoresis_core.logging_config import get_logger, setup_logging


def test_get_logger_returns_callable_logger() -> None:
    logger = get_logger("test.module")
    logger.info("smoke test")  # no exception
    assert logger is not None


def test_setup_logging_is_idempotent() -> None:
    setup_logging()
    setup_logging()  # second call is a no-op
