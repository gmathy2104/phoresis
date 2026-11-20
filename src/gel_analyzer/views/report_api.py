"""
Report API endpoints.

Provides synchronous report generation endpoints that accept
client-captured chart images (base64 PNG) and return Word documents.

Endpoints:
- POST /api/analyses/<uuid>/report/generate/ - Generate analysis report
- POST /api/comparisons/<uuid>/report/generate/ - Generate comparison report
- POST /api/analyses/<uuid>/densitometry/report/generate/ - Generate densitometry report
"""

from __future__ import annotations

import base64
import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.access import saved_comparisons_readable_by
from gel_analyzer.models import GelAnalysis, SavedComparison
from gel_analyzer.services.report import (
    GelAnalysisReportBuilder,
    ReportDataCollector,
)
from gel_analyzer.services.report.comparison_builder import (
    ComparisonReportBuilder,
)
from gel_analyzer.services.report.comparison_data_collector import (
    ComparisonDataCollector,
)
from gel_analyzer.services.report.comparison_excel_builder import (
    ComparisonExcelBuilder,
)
from gel_analyzer.services.report.comparison_pptx_builder import (
    ComparisonPowerPointBuilder,
)
from gel_analyzer.services.report.constants import (
    ALL_SECTION_KEYS,
    DENSITOMETRY_ALL_SECTION_KEYS,
    FORMAT_CONTENT_TYPES,
    FORMAT_EXTENSIONS,
    REPORT_FORMATS,
)
from gel_analyzer.services.report.densitometry_builder import (
    DensitometryReportBuilder,
)
from gel_analyzer.services.report.densitometry_data_collector import (
    DensitometryDataCollector,
)
from gel_analyzer.services.report.densitometry_excel_builder import (
    DensitometryExcelBuilder,
)
from gel_analyzer.services.report.densitometry_pptx_builder import (
    DensitometryPowerPointBuilder,
)
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _decode_images(images_data: dict) -> dict:
    """
    Decode base64 image data from the frontend into bytes.

    Handles nested structures:
    - Top-level keys: gel_overview, overlay_electropherogram, etc.
    - Nested lanes dict: lanes -> lane_number -> image_key -> base64

    Args:
        images_data: Dict of image keys to base64 data URI strings.

    Returns:
        Dict of image keys to bytes (decoded PNG data).
    """
    decoded = {}

    for key, value in images_data.items():
        if value is None:
            continue

        if key == "lanes" and isinstance(value, dict):
            # Decode per-lane images
            for lane_key, lane_images in value.items():
                if not isinstance(lane_images, dict):
                    continue
                for img_key, img_data in lane_images.items():
                    if img_data and isinstance(img_data, str):
                        flat_key = f"lane_{lane_key}_{img_key}"
                        decoded[flat_key] = _decode_base64(img_data)

        elif key == "gel_images" and isinstance(value, dict):
            # Decode per-analysis gel images
            for analysis_id, img_data in value.items():
                if img_data and isinstance(img_data, str):
                    flat_key = f"gel_image_{analysis_id}"
                    decoded[flat_key] = _decode_base64(img_data)

        elif isinstance(value, str):
            decoded[key] = _decode_base64(value)

    return decoded


def _decode_base64(data_uri: str) -> bytes | None:
    """
    Decode a base64 data URI to bytes.

    Handles both:
    - Full data URI: "data:image/png;base64,iVBOR..."
    - Raw base64: "iVBOR..."

    Returns None if decoding fails.
    """
    try:
        if "," in data_uri:
            # Strip data URI prefix
            _, encoded = data_uri.split(",", 1)
        else:
            encoded = data_uri

        return base64.b64decode(encoded)
    except Exception as e:
        logger.warning(f"Failed to decode base64 image: {e}")
        return None


@login_required
@require_http_methods(["POST"])
def api_generate_analysis_report(request, pk: UUID):
    """
    Generate Word report for a gel analysis.

    Accepts client-captured chart images as base64 PNGs in the request body,
    queries the database for metadata/tables, and returns a .docx file.

    POST /api/analyses/<uuid>/report/generate/

    Request body (JSON):
        {
            "images": {
                "gel_overview": "data:image/png;base64,...",
                "lanes": {
                    "1": {
                        "electropherogram_2d": "data:image/png;base64,...",
                        "electropherogram_3d": "data:image/png;base64,...",
                        "digital_lane": "data:image/png;base64,..."
                    },
                    ...
                }
            }
        }

    Response: .docx file download
    """
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image", "created_by"),
        pk=pk,
    )

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {"error": "Invalid JSON body"},
            status=400,
        )

    images_data = body.get("images", {})
    if not images_data:
        return JsonResponse(
            {"error": "No images provided. Capture panels before generating report."},
            status=400,
        )

    # Decode base64 images
    decoded_images = _decode_images(images_data)
    logger.info(f"Report generation: analysis={analysis.name}, images_received={len(decoded_images)}")

    # Collect data from database
    collector = ReportDataCollector()
    data = collector.collect(analysis, request.user)

    # Build Word document
    builder = GelAnalysisReportBuilder(data, decoded_images)
    doc_buffer = builder.build()

    # Generate filename
    name = analysis.name.replace(" ", "_")[:30] if analysis.name else "analysis"
    filename = f"gel_report_{name}.docx"

    # Return as file download
    response = HttpResponse(
        doc_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    logger.info(f"Report generated: {filename}")
    return response


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
            ]
        }

    Response: File download with appropriate Content-Type
    """
    # A private comparison is its creator's (gel_analyzer/access.py): another account gets a 404.
    comparison = get_object_or_404(
        saved_comparisons_readable_by(request.user, SavedComparison.objects.select_related("created_by")),
        pk=pk,
    )

    # Parse optional JSON body
    report_format = "docx"
    sections = None
    band_overlay = True

    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}

        report_format = body.get("format", "docx")
        sections = body.get("sections")
        band_overlay = body.get("band_overlay", True)

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

    logger.info(
        f"Comparison report generation: comparison={comparison.name}, format={report_format}, sections={sections}"
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
        builder = ComparisonPowerPointBuilder(data, sections=sections, band_overlay=band_overlay)

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
            "band_overlay": true                    // default: true
        }

    Response: File download with appropriate Content-Type
    """
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image", "created_by"),
        pk=pk,
    )

    # Parse optional JSON body
    report_format = "docx"
    sections = None
    band_overlay = True

    if request.body:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            body = {}

        report_format = body.get("format", "docx")
        sections = body.get("sections")
        band_overlay = body.get("band_overlay", True)

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

    logger.info(
        f"Densitometry report generation: analysis={analysis.name}, format={report_format}, sections={sections}"
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
        builder = DensitometryPowerPointBuilder(data, sections=sections, band_overlay=band_overlay)

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
