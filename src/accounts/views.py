"""Views for the accounts app."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .forms import PhoresisLoginForm


class PhoresisLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PhoresisLoginForm
    redirect_authenticated_user = True


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/profile.html")
