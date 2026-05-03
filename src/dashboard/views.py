"""Dashboard views — Phase 1 stub."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/home.html")
