"""
Print-friendly views for headless-Chromium PDF rendering.

These views are designed to be loaded by the Playwright renderer
(``phoresis_core.reporting.playwright_renderer``) — they output the
same data the user sees on screen, but stripped of nav / sidebars and
laid out for an A4 page via a print stylesheet.

Authentication: the views accept either:
  - the user's normal session cookie (so a developer can hit them in
    a browser to debug the layout), or
  - a one-shot signed token in the ``?token=`` query string, minted by
    :func:`phoresis_core.reporting.print_token.issue_print_token` and
    forwarded by the worker. The token must be scoped to the resource
    being printed (``analysis:<uuid>`` / ``comparison:<uuid>``).

URL conventions (used by the PDF builder):
  - ``/analyses/<uuid>/report/print/``
  - ``/comparisons/<uuid>/report/print/``
  - ``/analyses/<uuid>/densitometry/report/print/``
"""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from gel_analyzer.models import GelAnalysis, SavedComparison
from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector
from gel_analyzer.services.report.data_collector import ReportDataCollector
from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector
from phoresis_core.logging_config import get_logger
from phoresis_core.reporting.print_token import PrintTokenError, verify_print_token

logger = get_logger(__name__)

User = get_user_model()


def _authenticate(request, expected_scope: str) -> bool:
    """Allow the request through if the user is logged in OR a valid
    one-shot token bound to ``expected_scope`` is present in the
    query string. Returns ``True`` when the request is authorised.
    """
    if request.user.is_authenticated:
        return True
    token = request.GET.get("token")
    if not token:
        return False
    try:
        payload = verify_print_token(token, expected_scope=expected_scope)
    except PrintTokenError as exc:
        logger.warning(f"print token rejected: {exc}")
        return False
    # Attach the user lazily so downstream code (data collectors) sees
    # the same user object the original request would have had.
    try:
        request.user = User.objects.get(pk=int(payload["sub"]))
    except (User.DoesNotExist, ValueError, KeyError):
        return False
    return True


def comparison_report_print_view(request, pk: UUID):
    """Render the comparison report as a single, print-friendly HTML page."""
    if not _authenticate(request, expected_scope=f"comparison:{pk}"):
        return HttpResponseForbidden("authentication required")

    comparison = get_object_or_404(
        SavedComparison.objects.select_related("created_by"), pk=pk
    )
    data = ComparisonDataCollector().collect(comparison, request.user)

    context = {
        "data": data,
        "comparison": comparison,
        "scope": f"comparison:{pk}",
    }
    return render(request, "gel_analyzer/reports/comparison_print.html", context)


def analysis_report_print_view(request, pk: UUID):
    """Render the single-analysis report as a print-friendly HTML page."""
    if not _authenticate(request, expected_scope=f"analysis:{pk}"):
        return HttpResponseForbidden("authentication required")

    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image", "created_by"), pk=pk
    )
    data = ReportDataCollector().collect(analysis, request.user)

    context = {
        "data": data,
        "analysis": analysis,
        "scope": f"analysis:{pk}",
    }
    return render(request, "gel_analyzer/reports/analysis_print.html", context)


def densitometry_report_print_view(request, pk: UUID):
    """Render the densitometry report as a print-friendly HTML page."""
    if not _authenticate(request, expected_scope=f"analysis:{pk}"):
        return HttpResponseForbidden("authentication required")

    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image", "created_by"), pk=pk
    )
    data = DensitometryDataCollector().collect(analysis, request.user)

    context = {
        "data": data,
        "analysis": analysis,
        "scope": f"analysis:{pk}",
    }
    return render(request, "gel_analyzer/reports/densitometry_print.html", context)
