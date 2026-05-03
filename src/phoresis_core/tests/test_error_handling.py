"""Tests for phoresis_core.error_handling — utils, model, middleware."""

import datetime as dt
import re
from unittest.mock import MagicMock

import pytest

from phoresis_core.error_handling.middleware import ExceptionContextMiddleware
from phoresis_core.error_handling.utils import (
    extract_app_label,
    generate_error_id,
    generate_error_signature,
    get_client_ip,
    sanitize_dict,
)
from phoresis_core.models import ErrorLog


def test_generate_error_id_format() -> None:
    eid = generate_error_id()
    assert re.fullmatch(r"PHOR-\d{8}-[A-F0-9]{6}", eid), eid


def test_generate_error_signature_is_deterministic() -> None:
    a = generate_error_signature("ValueError", "/x/y.py", "f", 10)
    b = generate_error_signature("ValueError", "/x/y.py", "f", 10)
    c = generate_error_signature("KeyError", "/x/y.py", "f", 10)
    assert a == b
    assert a != c
    assert len(a) == 32  # md5 hex


def test_sanitize_dict_redacts_sensitive_keys() -> None:
    data = {"username": "alice", "password": "secret", "nested": {"api_key": "k"}}
    sanitized = sanitize_dict(data)
    assert sanitized["username"] == "alice"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"


def test_sanitize_dict_truncates_long_strings() -> None:
    data = {"text": "x" * 2000}
    sanitized = sanitize_dict(data, max_value_length=100)
    assert sanitized["text"].endswith("[TRUNCATED]")
    assert len(sanitized["text"]) <= 130  # 100 + "...[TRUNCATED]"


def test_get_client_ip_prefers_x_forwarded_for() -> None:
    request = MagicMock()
    request.META = {"HTTP_X_FORWARDED_FOR": "203.0.113.1, 10.0.0.1", "REMOTE_ADDR": "10.0.0.2"}
    assert get_client_ip(request) == "203.0.113.1"


def test_get_client_ip_falls_back_to_remote_addr() -> None:
    request = MagicMock()
    request.META = {"REMOTE_ADDR": "192.168.1.1"}
    assert get_client_ip(request) == "192.168.1.1"


def test_extract_app_label_handles_none() -> None:
    assert extract_app_label(None) is None
    assert extract_app_label("") is None


def test_extract_app_label_returns_none_for_site_packages() -> None:
    assert extract_app_label("/usr/lib/.venv/site-packages/django/db/base.py") is None


@pytest.mark.django_db
def test_error_log_can_be_created() -> None:
    log = ErrorLog.objects.create(level="ERROR", message="boom", source_type=ErrorLog.SOURCE_TYPE_HTTP)
    assert log.pk is not None
    assert log.level == "ERROR"
    assert log.timestamp <= dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)


@pytest.mark.django_db
def test_exception_middleware_attaches_error_context_to_request(rf) -> None:
    middleware = ExceptionContextMiddleware(get_response=lambda r: None)
    request = rf.get("/some/path/")
    request._error_context = None  # mimic __call__ initialisation
    request.user = MagicMock(is_authenticated=False)

    middleware.process_exception(request, ValueError("bad"))

    ctx = request._error_context
    assert ctx is not None
    assert ctx["exception_type"] == "ValueError"
    assert ctx["exception_message"] == "bad"
    assert ctx["http_method"] == "GET"
    assert ctx["request_path"] == "/some/path/"
    assert re.fullmatch(r"PHOR-\d{8}-[A-F0-9]{6}", ctx["error_id"])
