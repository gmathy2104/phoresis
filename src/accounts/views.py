"""Views for the accounts app."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .forms import PhoresisLoginForm


class PhoresisLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PhoresisLoginForm
    redirect_authenticated_user = True


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/profile.html")


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
