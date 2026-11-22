"""Views for the accounts app."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import PhoresisLoginForm
from .security import has_two_factor, requires_two_factor
from .two_factor import backup_codes_left


class PhoresisLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PhoresisLoginForm
    redirect_authenticated_user = True


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    enrolled = has_two_factor(user)
    return render(
        request,
        "accounts/profile.html",
        {
            "two_factor_on": enrolled,
            "two_factor_required": requires_two_factor(user),
            "backup_codes_left": backup_codes_left(user) if enrolled else 0,
            # Outcome of the last action, carried in the query string (the pages show no flash messages).
            "two_factor_notice": request.GET.get("two_factor", ""),
            "password_changed": request.GET.get("password") == "changed",
        },
    )


class PhoresisPasswordChangeView(PasswordChangeView):
    """Change one's own password; the new one goes through AUTH_PASSWORD_VALIDATORS.

    Django keeps this session signed in and signs out every other session of the user.
    """

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_success_url(self) -> str:
        return f"{super().get_success_url()}?password=changed"


@require_POST
@login_required
def theme_set_view(request: HttpRequest) -> HttpResponse:
    """Persist the user's theme preference (auto / light / dark)."""
    value = request.POST.get("theme", "").strip()
    if value not in ("auto", "light", "dark"):
        return HttpResponseBadRequest("invalid theme")
    profile = request.user.profile
    profile.theme = value
    profile.save(update_fields=["theme", "updated_at"])
    return HttpResponse(status=204)
