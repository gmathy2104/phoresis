"""Ph0: orphaned analysis-report client-capture path is fully removed."""

from pathlib import Path

import pytest

from django.conf import settings
from django.urls import NoReverseMatch, reverse


def test_orphaned_analysis_report_url_name_is_gone():
    with pytest.raises(NoReverseMatch):
        reverse("gel_analyzer:api_generate_analysis_report", args=["x"])


def test_orphaned_view_symbol_not_exported():
    import gel_analyzer.views as views

    assert not hasattr(views, "api_generate_analysis_report")


def test_report_capture_js_file_deleted():
    js = Path(settings.SRC_DIR) / "gel_analyzer" / "static" / "gel_analyzer" / "js" / "report" / "report-capture.js"
    assert not js.exists(), "report-capture.js should be deleted"


def test_densitometry_template_no_longer_references_capture_js():
    tpl = Path(settings.SRC_DIR) / "gel_analyzer" / "templates" / "gel_analyzer" / "analyses" / "densitometry.html"
    text = tpl.read_text(encoding="utf-8")
    assert "report-capture.js" not in text


def test_surviving_report_endpoints_still_resolve():
    # The two server-side endpoints must remain.
    assert reverse(
        "gel_analyzer:api_generate_densitometry_report",
        args=["00000000-0000-0000-0000-000000000000"],
    )
    assert reverse(
        "gel_analyzer:api_generate_comparison_report",
        args=["00000000-0000-0000-0000-000000000000"],
    )
