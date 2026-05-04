"""Utility helpers for error handling."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from functools import lru_cache
from typing import Any

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "credit_card",
        "creditcard",
        "cc",
        "cvv",
        "ssn",
        "csrfmiddlewaretoken",
        "sessionid",
        "key",
        "private",
        "access_token",
        "refresh_token",
        "bearer",
        "credential",
    }
)


def generate_error_id() -> str:
    """Return a unique human-readable error reference (`PHOR-YYYYMMDD-XXXXXX`)."""
    return f"PHOR-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def generate_error_signature(
    exception_type: str, pathname: str | None, func_name: str | None, lineno: int | None
) -> str:
    """Return an md5 signature for deduplication."""
    parts = [exception_type or "", pathname or "", func_name or "", str(lineno) if lineno else ""]
    return hashlib.md5(":".join(parts).encode()).hexdigest()


def sanitize_dict(data: Any, max_depth: int = 3, max_value_length: int = 1000, _current_depth: int = 0) -> Any:
    """Redact sensitive keys, truncate long strings, cap recursion."""
    if _current_depth >= max_depth:
        return "[MAX_DEPTH_REACHED]"
    if data is None:
        return None
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            key_str = str(key).lower()
            if any(s in key_str for s in SENSITIVE_KEYS):
                out[key] = "[REDACTED]"
            elif isinstance(value, dict):
                out[key] = sanitize_dict(value, max_depth, max_value_length, _current_depth + 1)
            elif isinstance(value, list | tuple):
                out[key] = [
                    sanitize_dict(item, max_depth, max_value_length, _current_depth + 1)
                    if isinstance(item, dict | list | tuple)
                    else item
                    for item in value
                ]
            elif isinstance(value, str) and len(value) > max_value_length:
                out[key] = value[:max_value_length] + "...[TRUNCATED]"
            else:
                out[key] = value
        return out
    if isinstance(data, list | tuple):
        return [
            sanitize_dict(item, max_depth, max_value_length, _current_depth + 1)
            if isinstance(item, dict | list | tuple)
            else item
            for item in data
        ]
    return data


def get_client_ip(request) -> str | None:
    """Return the client IP, preferring X-Forwarded-For over REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
    if ip and ":" in ip and "." in ip:
        ip = ip.split(":")[0]
    return ip or None


def truncate_string(value: str, max_length: int = 500) -> str:
    if not value or len(value) <= max_length:
        return value
    return value[:max_length] + "..."


@lru_cache(maxsize=1)
def _local_app_labels() -> frozenset:
    from django.apps import apps
    from django.conf import settings

    base_dir = str(getattr(settings, "BASE_DIR", "")).replace("\\", "/").lower()
    if not base_dir:
        return frozenset()
    labels = set()
    for app_config in apps.get_app_configs():
        app_path = str(getattr(app_config, "path", "")).replace("\\", "/").lower()
        if app_path.startswith(base_dir):
            labels.add(app_config.label)
    return frozenset(labels)


def extract_app_label(pathname: str | None) -> str | None:
    """Derive a Django app_label from a file path, or None if outside local apps."""
    if not pathname:
        return None
    normalized = pathname.replace("\\", "/").lower()
    if "/.venv/" in normalized or "/site-packages/" in normalized:
        return None
    labels = _local_app_labels()
    if not labels:
        return None
    for segment in normalized.split("/"):
        if segment in labels:
            return segment
    return None
