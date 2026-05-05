"""
Densitometry view for gel analysis.

Provides the main densitometry interface for quantitative band analysis.
This is a separate module from the annotation editor with its own template.
"""

import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.safestring import mark_safe

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    GelAnalysis,
    LadderTemplate,
    Lane,
    LaneDensitometrySummary,
)
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


@login_required
def densitometry_view(request, pk):
    """
    Main densitometry analysis view.

    Displays the 4-panel UI for quantitative gel analysis:
    - Gel overview (top-left)
    - Electropherogram (top-right)
    - Band detail/digital lane (bottom-left)
    - Measurements table (bottom-right)

    Args:
        request: HTTP request
        pk: GelAnalysis UUID

    Returns:
        Rendered template
    """
    # Prefetch bands with their densitometry results
    bands_prefetch = Prefetch("bands", queryset=Band.objects.select_related("densitometry").order_by("position_y"))

    # Prefetch lanes with densitometry summaries and bands
    lanes_prefetch = Prefetch(
        "lanes",
        queryset=Lane.objects.select_related("densitometry_summary")
        .prefetch_related(bands_prefetch)
        .annotate(band_count_annotated=Count("bands"))
        .order_by("lane_number"),
    )

    analysis = get_object_or_404(
        GelAnalysis.objects.select_related(
            "gel_image",
            "created_by",
        ).prefetch_related(
            lanes_prefetch,
            "ladder_calibrations__template",
        ),
        pk=pk,
    )

    # Check if densitometry results exist
    has_results = LaneDensitometrySummary.objects.filter(lane__analysis=analysis).exists()

    # Build lane and band data from prefetched relations (single pass)
    lanes = []
    bands = []

    for lane in analysis.lanes.all():
        # Lane data
        lane_data = {
            "id": lane.id,
            "lane_number": lane.lane_number,
            "lane_type": lane.lane_type,
            "sample_name": lane.sample_name or lane.display_name,
            "band_count": lane.band_count_annotated,
            "bbox": lane.bbox,
        }

        # Add densitometry summary if available (already prefetched)
        try:
            summary = lane.densitometry_summary
            lane_data["densitometry"] = {
                "total_area": summary.total_integrated_area,
                "poi_percentage": summary.poi_percentage,
                "band_count": summary.band_count,
            }
        except LaneDensitometrySummary.DoesNotExist:
            lane_data["densitometry"] = None

        lanes.append(lane_data)

        # Band data (already prefetched with densitometry)
        for band in lane.bands.all():
            band_data = {
                "id": str(band.id),
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                "band_type": band.band_type,
                "detection_source": band.detection_source,
                "position_y": band.position_y,
                "estimated_mw_kda": band.estimated_mw_kda,
                "bbox": band.bbox,
            }

            # Add densitometry if available (already prefetched)
            try:
                densitometry = band.densitometry
                band_data["densitometry"] = {
                    "corrected_area": densitometry.corrected_area,
                    "relative_percent_lane": densitometry.relative_percent_lane,
                    "fit_r_squared": densitometry.fit_r_squared,
                }
            except DensitometryResult.DoesNotExist:
                band_data["densitometry"] = None

            bands.append(band_data)

    # Serialize analysis-level calibration data for MW axis mode
    calibration_data = None
    calibration = analysis.ladder_calibrations.first()
    if calibration:
        calibration_data = {
            "method": calibration.method,
            "coefficients": calibration.coefficients,
            "r_squared": float(calibration.r_squared) if calibration.r_squared else None,
            "template_name": calibration.template.name if calibration.template else None,
            "mw_range": {
                "min": float(calibration.template.mw_range_min)
                if calibration.template and calibration.template.mw_range_min
                else None,
                "max": float(calibration.template.mw_range_max)
                if calibration.template and calibration.template.mw_range_max
                else None,
            }
            if calibration.template
            else None,
        }

    # Get available ladder templates for MW axis
    ladder_templates = list(LadderTemplate.objects.filter(is_active=True).values("id", "name", "manufacturer"))

    # Build lane IDs CSV for comparison link
    lane_ids_csv = ",".join(str(lane["id"]) for lane in lanes)

    context = {
        "analysis": analysis,
        "gel_image": analysis.gel_image,
        # Serialize as JSON to handle None -> null conversion for JavaScript
        "lanes": mark_safe(json.dumps(lanes)),
        "bands": mark_safe(json.dumps(bands)),
        "has_results": has_results,
        "calibration_json": mark_safe(json.dumps(calibration_data)),
        "ladder_templates": ladder_templates,
        "lane_count": len(lanes),
        "band_count": len(bands),
        "lane_ids_csv": lane_ids_csv,
        # URLs for API calls
        "api_urls": {
            "densitometry": reverse("gel_analyzer:api_densitometry", kwargs={"pk": analysis.id}),
            "run": reverse("gel_analyzer:api_run_densitometry", kwargs={"pk": analysis.id}),
            "run_async": reverse("gel_analyzer:api_run_densitometry_async", kwargs={"pk": analysis.id}),
            "export": reverse("gel_analyzer:api_export_densitometry", kwargs={"pk": analysis.id}),
        },
        # Page settings
        "page_title": f"Densitometry - {analysis.name}",
    }

    return render(request, "gel_analyzer/analyses/densitometry.html", context)
