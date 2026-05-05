"""
PDF report builder.

Delegates to the headless-Chromium renderer in
``phoresis_core.reporting.playwright_renderer``: the worker mints a
short-lived print token, builds the URL of the matching ``…/report/print/``
view, and Playwright loads it + dumps the resulting page to PDF.

The PDF is therefore pixel-identical to what a developer sees when
opening the same print URL in a logged-in browser session — the
Tailwind output.css that the rest of the app uses is the single source
of visual truth, no Pillow re-render involved.
"""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from phoresis_core.logging_config import get_logger
from phoresis_core.reporting import issue_print_token, render_page_pdf

logger = get_logger(__name__)


def _absolute_url(path: str, query: dict[str, str] | None = None) -> str:
    """Compose an absolute URL the headless browser can hit.

    Honours :setting:`PHORESIS_INTERNAL_BASE_URL` so the worker can talk
    to the web container directly (``http://web:8000``) instead of
    going through Caddy + the public hostname. Falls back to
    ``http://127.0.0.1:8000`` for the dev server.
    """
    base = getattr(settings, "PHORESIS_INTERNAL_BASE_URL", "") or "http://127.0.0.1:8000"
    base = base.rstrip("/")
    if query:
        path = f"{path}?{urlencode(query)}"
    return f"{base}{path}"


def build_analysis_pdf(analysis_id, user) -> BytesIO:
    """Render the single-analysis report as PDF."""
    return _build_pdf(
        url_name="gel_analyzer:analysis_report_print",
        kwargs={"pk": analysis_id},
        scope=f"analysis:{analysis_id}",
        user=user,
    )


def build_comparison_pdf(comparison_id, user) -> BytesIO:
    """Render the comparison report as PDF."""
    return _build_pdf(
        url_name="gel_analyzer:comparison_report_print",
        kwargs={"pk": comparison_id},
        scope=f"comparison:{comparison_id}",
        user=user,
    )


def build_densitometry_pdf(analysis_id, user) -> BytesIO:
    """Render the densitometry report as PDF."""
    return _build_pdf(
        url_name="gel_analyzer:densitometry_report_print",
        kwargs={"pk": analysis_id},
        scope=f"analysis:{analysis_id}",
        user=user,
    )


def _build_pdf(*, url_name: str, kwargs: dict, scope: str, user) -> BytesIO:
    token = issue_print_token(user_id=user.pk, scope=scope)
    path = reverse(url_name, kwargs=kwargs)
    url = _absolute_url(path, query={"token": token})
    logger.info(f"Rendering PDF via Playwright: {url_name} scope={scope}")
    pdf_bytes = render_page_pdf(url, wait_selector=".report-section")
    return BytesIO(pdf_bytes)
