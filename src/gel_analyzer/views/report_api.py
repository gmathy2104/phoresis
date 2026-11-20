"""
Report API endpoints.

Provides synchronous, server-rendered report generation endpoints.

Endpoints:
- POST /api/comparisons/<uuid>/report/generate/ - Generate comparison report
- POST /api/analyses/<uuid>/densitometry/report/generate/ - Generate densitometry report
"""

from __future__ import annotations

import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.access import saved_comparisons_readable_by
from gel_analyzer.models import GelAnalysis, SavedComparison
from gel_analyzer.services.report.comparison_builder import ComparisonReportBuilder
from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector
from gel_analyzer.services.report.comparison_excel_builder import ComparisonExcelBuilder
from gel_analyzer.services.report.comparison_pptx_builder import ComparisonPowerPointBuilder
from gel_analyzer.services.report.constants import (
    ALL_SECTION_KEYS,
    DENSITOMETRY_ALL_SECTION_KEYS,
    FORMAT_CONTENT_TYPES,
    FORMAT_EXTENSIONS,
    GEL_VARIANTS_ALLOWED,
    GEL_VARIANTS_CANONICAL_ORDER,
    GEL_VARIANTS_DEFAULT,
    REPORT_FORMATS,
)
from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder
from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector
from gel_analyzer.services.report.densitometry_excel_builder import DensitometryExcelBuilder
from gel_analyzer.services.report.densitometry_pptx_builder import DensitometryPowerPointBuilder
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _parse_gel_variants(raw):
    """Validate + normalise the report body's ``gel_variants`` (spec D3).

    Returns ``(gel_variants, error_response_or_None)``. Accepts a list of
    "LANES_ONLY"|"KEY_BANDS"|"FULL"; rejects non-lists and unknown values with
    a 400. Absent/empty defaults to ["FULL"]. Output is in canonical order
    LANES_ONLY -> KEY_BANDS -> FULL.
    """
    if raw is None:
        return list(GEL_VARIANTS_DEFAULT), None
    if not isinstance(raw, list):
        return None, JsonResponse({"error": "gel_variants must be a list"}, status=400)
    invalid = [v for v in raw if v not in GEL_VARIANTS_ALLOWED]
    if invalid:
        return None, JsonResponse(
            {"error": f"Invalid gel_variants: {', '.join(str(v) for v in invalid)}"},
            status=400,
        )
    selected = set(raw)
    ordered = [v for v in GEL_VARIANTS_CANONICAL_ORDER if v in selected]
    return (ordered or list(GEL_VARIANTS_DEFAULT)), None


@login_required
@require_http_methods(["POST"])
def api_generate_comparison_report(request, pk: UUID):
    """
    Generate a report for a saved lane comparison.

    All visuals (gel images, digital gel, electropherograms) are rendered
    server-side with Pillow/matplotlib. No client-side image capture needed.

    POST /api/comparisons/<uuid>/report/generate/

    Request body (JSON, all fields optional):
        {
            "format": "docx" | "xlsx" | "pptx",   // default: "docx"
            "sections": [                           // default: all
                "overview", "sample_summary", "digital_gel", "gel_images",
                "band_comparison", "lane_details", "poi_purity", "materials_methods"
            ],
            "gel_variants": [                       // default: ["FULL"]
                "LANES_ONLY", "KEY_BANDS", "FULL"   // one PPTX gel slide each / analysis
            ]
        }

    Response: File download with appropriate Content-Type

    A report is a READ: only of a comparison the caller may open -- their own, or a
    public one (``gel_analyzer/access.py``). Another account's private comparison is
    the same 404 as an unknown pk.
    """
    comparison = get_object_or_404(
        saved_comparisons_readable_by(request.user, SavedComparison.objects.select_related("created_by")),
        pk=pk,
    )

    # Parse optional JSON body
    report_format = "docx"
    sections = None
    band_overlay = True
    gel_variants_raw = None

    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}

        report_format = body.get("format", "docx")
        sections = body.get("sections")
        band_overlay = body.get("band_overlay", True)
        gel_variants_raw = body.get("gel_variants")

    # Validate format
    if report_format not in REPORT_FORMATS:
        return JsonResponse(
            {"error": f"Invalid format. Must be one of: {', '.join(REPORT_FORMATS)}"},
            status=400,
        )

    # Validate sections
    if sections is not None:
        if not isinstance(sections, list):
            return JsonResponse({"error": "sections must be a list"}, status=400)
        invalid = [s for s in sections if s not in ALL_SECTION_KEYS]
        if invalid:
            return JsonResponse(
                {"error": f"Invalid section keys: {', '.join(invalid)}"},
                status=400,
            )

    # Validate gel_variants (spec D3 — one gel slide per selected variant)
    gel_variants, gv_error = _parse_gel_variants(gel_variants_raw)
    if gv_error is not None:
        return gv_error

    logger.info(
        f"Comparison report generation: comparison={comparison.name}, "
        f"format={report_format}, sections={sections}, gel_variants={gel_variants}"
    )

    # Collect data from database
    collector = ComparisonDataCollector()
    data = collector.collect(comparison, request.user)

    # Dispatch to correct builder
    if report_format == "docx":
        builder = ComparisonReportBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == "xlsx":
        builder = ComparisonExcelBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == "pptx":
        builder = ComparisonPowerPointBuilder(
            data, sections=sections, band_overlay=band_overlay, gel_variants=gel_variants
        )

    doc_buffer = builder.build()

    # Generate filename
    name = comparison.name.replace(" ", "_")[:30] if comparison.name else "comparison"
    ext = FORMAT_EXTENSIONS[report_format]
    filename = f"comparison_report_{name}{ext}"
    content_type = FORMAT_CONTENT_TYPES[report_format]

    # Return as file download
    response = HttpResponse(
        doc_buffer.getvalue(),
        content_type=content_type,
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    logger.info(f"Comparison report generated: {filename}")
    return response


@login_required
@require_http_methods(["POST"])
def api_generate_densitometry_report(request, pk: UUID):
    """
    Generate a report for a densitometry analysis.

    All visuals (gel images, digital gel, electropherograms, terrain charts)
    are rendered server-side with Pillow/matplotlib. No client-side image
    capture needed.

    POST /api/analyses/<uuid>/densitometry/report/generate/

    Request body (JSON, all fields optional):
        {
            "format": "docx" | "xlsx" | "pptx",   // default: "docx"
            "sections": [                           // default: all
                "overview", "sample_summary", "gel_image", "digital_gel",
                "poi_purity", "lane_details", "terrain_view", "materials_methods"
            ],
            "band_overlay": true,                   // default: true (Word builder)
            "gel_variants": [                       // default: ["FULL"]
                "LANES_ONLY", "KEY_BANDS", "FULL"   // one PPTX gel slide each
            ]
        }

    Response: File download with appropriate Content-Type
    """
    analysis = get_object_or_404(
        # gel_image__assay: the collector suffixes the anti-HCP reference lane " (reference)"
        GelAnalysis.objects.select_related("gel_image__assay", "created_by"),
        pk=pk,
    )

    # Parse optional JSON body
    report_format = "docx"
    sections = None
    band_overlay = True
    gel_variants_raw = None

    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}

        report_format = body.get("format", "docx")
        sections = body.get("sections")
        band_overlay = body.get("band_overlay", True)
        gel_variants_raw = body.get("gel_variants")

    # Validate format
    if report_format not in REPORT_FORMATS:
        return JsonResponse(
            {"error": f"Invalid format. Must be one of: {', '.join(REPORT_FORMATS)}"},
            status=400,
        )

    # Validate sections
    if sections is not None:
        if not isinstance(sections, list):
            return JsonResponse({"error": "sections must be a list"}, status=400)
        invalid = [s for s in sections if s not in DENSITOMETRY_ALL_SECTION_KEYS]
        if invalid:
            return JsonResponse(
                {"error": f"Invalid section keys: {', '.join(invalid)}"},
                status=400,
            )

    # Validate gel_variants (spec D3 — one gel slide per selected variant)
    gel_variants, gv_error = _parse_gel_variants(gel_variants_raw)
    if gv_error is not None:
        return gv_error

    logger.info(
        f"Densitometry report generation: analysis={analysis.name}, "
        f"format={report_format}, sections={sections}, gel_variants={gel_variants}"
    )

    # Collect data from database
    collector = DensitometryDataCollector()
    data = collector.collect(analysis, request.user)

    # Dispatch to correct builder
    if report_format == "docx":
        builder = DensitometryReportBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == "xlsx":
        builder = DensitometryExcelBuilder(data, sections=sections, band_overlay=band_overlay)
    elif report_format == "pptx":
        builder = DensitometryPowerPointBuilder(
            data, sections=sections, band_overlay=band_overlay, gel_variants=gel_variants
        )

    doc_buffer = builder.build()

    # Generate filename
    name = analysis.name.replace(" ", "_")[:30] if analysis.name else "densitometry"
    ext = FORMAT_EXTENSIONS[report_format]
    filename = f"densitometry_report_{name}{ext}"
    content_type = FORMAT_CONTENT_TYPES[report_format]

    # Return as file download
    response = HttpResponse(
        doc_buffer.getvalue(),
        content_type=content_type,
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    logger.info(f"Densitometry report generated: {filename}")
    return response
