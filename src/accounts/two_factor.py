"""Two-factor views: set up an authenticator app, enter a code at sign-in, backup codes, turn off.

Built on django-otp (TOTPDevice + StaticDevice). `accounts.middleware.TwoFactorMiddleware` decides
who lands here; these views only run the steps.
"""

from __future__ import annotations

import base64
import re

import qrcode
import qrcode.image.svg
from django_otp import login as otp_login
from django_otp import match_token
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .security import has_two_factor, requires_two_factor

DEVICE_NAME = "Authenticator app"
BACKUP_CODE_COUNT = 10


def _next_url(request: HttpRequest) -> str:
    """Where to go once verified: the page first asked for, if it is one of ours."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return resolve_url(settings.LOGIN_REDIRECT_URL)


def _clean_token(raw: str) -> str:
    """A code as typed or pasted: spaces and dashes dropped (apps show '123 456')."""
    return re.sub(r"[\s-]", "", raw or "").lower()


def _qr_svg(data: str) -> str:
    """The provisioning URL as an inline SVG: no image file, no external service."""
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return image.to_string(encoding="unicode")


def _new_backup_codes(user) -> list[str]:
    """Replace the user's backup codes by fresh ones and return them, to be shown once."""
    with transaction.atomic():
        StaticDevice.objects.filter(user=user).delete()
        device = StaticDevice.objects.create(user=user, name="Backup codes", confirmed=True)
        codes = [StaticToken.random_token() for _ in range(BACKUP_CODE_COUNT)]
        StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return codes


def backup_codes_left(user) -> int:
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def remove_two_factor(user) -> int:
    """Delete every second factor of a user (turn off, or the operator's reset). Returns how many."""
    with transaction.atomic():
        removed, _ = TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()
    return removed


@never_cache
@login_required
def setup_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    if has_two_factor(user):
        # Already set up: adding a device needs a verified session, and there is one device per user.
        return redirect("accounts:profile" if user.is_verified() else "accounts:two_factor_verify")

    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("id").first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name=DEVICE_NAME, confirmed=False)

    error = ""
    if request.method == "POST":
        if device.verify_token(_clean_token(request.POST.get("token", ""))):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            codes = _new_backup_codes(user)
            otp_login(request, device)
            return render(
                request,
                "accounts/two_factor_codes.html",
                {"codes": codes, "next_url": _next_url(request), "first_time": True},
            )
        error = "That code is not valid. Check the clock of your phone, wait for the next code and try again."

    secret = base64.b32encode(device.bin_key).decode()
    return render(
        request,
        "accounts/two_factor_setup.html",
        {
            "qr_svg": mark_safe(_qr_svg(device.config_url)),  # noqa: S308 - generated here, not user input
            "secret": " ".join(secret[i : i + 4] for i in range(0, len(secret), 4)),
            "error": error,
            "next_url": _next_url(request),
            "required": requires_two_factor(user),
        },
    )


@never_cache
@login_required
def verify_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    next_url = _next_url(request)
    if user.is_verified() or not has_two_factor(user):
        return redirect(next_url)

    error = ""
    if request.method == "POST":
        device = match_token(user, _clean_token(request.POST.get("token", "")))
        if device is not None:
            otp_login(request, device)
            if isinstance(device, StaticDevice):
                # A backup code was spent: land where the number left is shown.
                return redirect("accounts:profile")
            return redirect(next_url)
        # django-otp slows down after each failure (1 s, 2 s, 4 s ...): a right code sent during that
        # delay is refused too, hence the wording.
        error = "That code is not valid, or it came too soon after a wrong one. Wait a few seconds and try again."

    return render(request, "accounts/two_factor_verify.html", {"error": error, "next_url": next_url})


@never_cache
@require_POST
@login_required
def backup_codes_view(request: HttpRequest) -> HttpResponse:
    """New backup codes; the previous ones stop working."""
    user = request.user
    if not user.is_verified():
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/two_factor_codes.html",
        {"codes": _new_backup_codes(user), "next_url": resolve_url("accounts:profile"), "first_time": False},
    )


@never_cache
@require_POST
@login_required
def disable_view(request: HttpRequest) -> HttpResponse:
    """Turn two-factor off: verified session, current password, and only where it is optional."""
    user = request.user
    if not user.is_verified() or requires_two_factor(user):
        return redirect("accounts:profile")
    if not user.check_password(request.POST.get("password", "")):
        return redirect(f"{resolve_url('accounts:profile')}?two_factor=wrong-password")
    remove_two_factor(user)
    return redirect(f"{resolve_url('accounts:profile')}?two_factor=off")
