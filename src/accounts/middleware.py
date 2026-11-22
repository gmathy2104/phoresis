"""Holds back a session that has passed the password but not the second factor.

Placed right after django-otp's OTPMiddleware. It covers every view at once (pages, the DRF API,
the Django admin, archived media): nothing has to remember a decorator.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .security import has_two_factor, requires_two_factor


class TwoFactorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or user.is_verified():
            return self.get_response(request)

        enrolled = has_two_factor(user)
        if not enrolled and not requires_two_factor(user):
            return self.get_response(request)

        # Enrolled: only the code page. Not enrolled but required: only the setup page. The setup page
        # is never open to an enrolled, unverified session, or a stolen password could add a device.
        target = reverse("accounts:two_factor_verify" if enrolled else "accounts:two_factor_setup")
        allowed = (target, reverse("accounts:logout"))
        if request.path in allowed or request.path.startswith(settings.STATIC_URL):
            return self.get_response(request)

        if request.headers.get("HX-Request"):
            response = HttpResponse(status=403)
            response["HX-Redirect"] = target
            return response
        if request.path.startswith("/api/"):
            return JsonResponse(
                {"detail": "Two-factor verification required.", "code": "two_factor_required"}, status=403
            )
        if request.method in ("GET", "HEAD"):
            return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return redirect(target)
