"""
One-shot signed tokens for the Playwright print session.

The Celery worker that renders the report cannot reuse the user's
browser session cookie (different process, different tab). Rather than
giving the worker a permanent service account or sharing the user's
session id, we mint a short-lived JWT bound to ``(user_id, scope, exp)``.
The renderer passes it to Chromium as a query string; a small middleware
on the print routes decodes and authenticates the request.

Tokens live for ``PRINT_TOKEN_TTL`` seconds (60 by default), are scoped
to a single resource (e.g. ``analysis:<uuid>``) and are signed with
``settings.SECRET_KEY``. They are NOT replay-protected on purpose —
inside that 60-second window the same Chromium tab may load several
sub-resources (CSS, fonts, the print page itself) that all need the
same token.

Reused by django-hub later — keep the API generic (no gel-specific
naming).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings

PRINT_TOKEN_TTL_SECONDS = 60
_ALGORITHM = "HS256"


class PrintTokenError(Exception):
    """Raised when a print token is missing, malformed, expired or scoped wrong."""


def issue_print_token(user_id: int | str, scope: str, ttl_seconds: int | None = None) -> str:
    """Mint a signed JWT for the given user + resource scope.

    Args:
        user_id: pk of the requesting user — written into the ``sub`` claim.
        scope: opaque string identifying the resource being printed,
            e.g. ``"analysis:abc-123"`` or ``"comparison:def"``. The
            print view checks this against its own resource id.
        ttl_seconds: override the default 60s lifetime (handy for tests).

    Returns:
        Compact JWT string suitable for use as a query-string parameter.
    """
    now = datetime.now(timezone.utc)
    ttl = ttl_seconds if ttl_seconds is not None else PRINT_TOKEN_TTL_SECONDS
    payload = {
        "sub": str(user_id),
        "scope": scope,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "purpose": "phoresis-print",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def verify_print_token(token: str, expected_scope: str | None = None) -> dict:
    """Decode and validate a print token.

    Args:
        token: the JWT received from the request.
        expected_scope: when provided, fail if ``payload["scope"]`` doesn't match.

    Returns:
        The decoded payload dict (``sub``, ``scope``, ``iat``, ``exp``).

    Raises:
        PrintTokenError: token missing/expired/wrong-purpose/wrong-scope.
    """
    if not token:
        raise PrintTokenError("missing print token")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise PrintTokenError("print token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise PrintTokenError(f"invalid print token: {exc}") from exc

    if payload.get("purpose") != "phoresis-print":
        raise PrintTokenError("token has wrong purpose")
    if expected_scope is not None and payload.get("scope") != expected_scope:
        raise PrintTokenError(
            f"token scope mismatch (expected {expected_scope!r}, got {payload.get('scope')!r})"
        )
    return payload
