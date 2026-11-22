"""Sign-in hardening helpers: who a failed login is counted against, and who must use two-factor.

Settings live in `phoresis.settings.base` (AXES_*, PHORESIS_REQUIRE_2FA); the operator's view is in
`accounts/docs/README.md`.
"""

from __future__ import annotations

import ipaddress

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest


def _is_proxy_address(address: str) -> bool:
    """True when `address` can only be our own reverse proxy: loopback (the Mac install) or a
    private network (the Docker bridge). No address at all (a unix socket) counts too."""
    if not address:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_ip(request: HttpRequest) -> str | None:
    """The browser's address, for the lockout counters.

    Gunicorn only ever hears Caddy, so REMOTE_ADDR is Caddy's address. Caddy appends the address it
    saw to X-Forwarded-For and discards whatever the client sent in that header (it trusts no
    upstream proxy), so the LAST entry is the one written by Caddy. The header is ignored when the
    connection does not come from a proxy address.
    """
    remote = request.META.get("REMOTE_ADDR") or ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    if forwarded and _is_proxy_address(remote):
        candidate = forwarded.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return remote or None


def axes_username(request: HttpRequest | None, credentials: dict | None = None) -> str:
    """The account a login attempt is counted against.

    The login accepts an email (any case) or a username: counted as typed, each spelling would get
    its own five tries. An email that matches an account is counted on that account's username, and
    everything is lower-cased.
    """
    typed = (credentials or {}).get("username")
    if typed is None and request is not None:
        typed = request.POST.get("username")
    typed = (typed or "").strip()
    if not typed:
        return ""
    user = get_user_model().objects.filter(email__iexact=typed).only("username").first()
    return (user.username if user else typed).lower()


def has_two_factor(user) -> bool:
    """True when the user has finished setting up an authenticator app."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def requires_two_factor(user) -> bool:
    """True when PHORESIS_REQUIRE_2FA makes two-factor mandatory for this user."""
    mode = settings.PHORESIS_REQUIRE_2FA
    if mode == "all":
        return True
    if mode == "staff":
        return bool(user.is_staff or user.is_superuser)
    return False
