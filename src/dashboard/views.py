"""Dashboard views."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .services import get_kpis, get_recent_gels


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "dashboard/home.html",
        {
            "kpis": get_kpis(),
            "recent_gels": get_recent_gels(),
        },
    )
