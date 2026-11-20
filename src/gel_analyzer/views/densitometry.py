"""
Densitometry view for gel analysis.

Provides the main densitometry interface for quantitative band analysis.
This is a separate module from the annotation editor with its own template.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from gel_analyzer.access import user_can_write_gel_analyzer
from gel_analyzer.models import (
    Band,
    DensitometryResult,
    GelAnalysis,
    LadderTemplate,
    Lane,
    LaneDensitometrySummary,
)
from gel_analyzer.services.analysis_detail import (
    HCP_TEXTS,
    VARIANT_TEXTS,
    band_number,
    band_role_map,
    page_summary,
    summary_payload,
)
from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL, is_final
from gel_analyzer.services.lane_geometry.shape import outline_of
from gel_analyzer.services.readout_publisher import assay_summary
from phoresis_core.logging_config import get_logger
from phoresis_core.safe_json import script_json

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
            "gel_image__assay",
            "created_by",
            "approved_by",
        ).prefetch_related(
            lanes_prefetch,
            "ladder_calibrations__template",
        ),
        pk=pk,
    )

    # Check if densitometry results exist
    has_results = LaneDensitometrySummary.objects.filter(lane__analysis=analysis).exists()

    # The readout, its lane values, checks and cards: the analysis page's own composition
    # (services/analysis_detail.py::page_summary), from the lanes prefetched above, whole.
    lanes_list = list(analysis.lanes.all())
    gel_summary = page_summary(analysis, lanes_list)
    roles = band_role_map(gel_summary, lanes_list)

    # Build lane and band data from prefetched relations (single pass)
    lanes = []
    bands = []
    # Lanes the HCP reference can be (spec §4.2): SAMPLE and CONTROL -- an HCP standard is often
    # typed CONTROL -- plus the current reference whatever its type, so the select never reads
    # "None" while one is set. Labels come from here, never from the JS lane names.
    reference_candidates = []

    for lane in lanes_list:
        if (
            lane.lane_type in (Lane.LaneType.SAMPLE, Lane.LaneType.CONTROL)
            or lane.id == analysis.readout_reference_lane_id
        ):
            sample = lane.sample_name
            reference_candidates.append(
                {
                    "id": lane.id,
                    "label": f"Lane {lane.lane_number} — {sample}" if sample else f"Lane {lane.lane_number}",
                }
            )

        # Lane data
        lane_data = {
            "id": lane.id,
            "lane_number": lane.lane_number,
            "lane_type": lane.lane_type,
            "sample_name": lane.sample_name or lane.display_name,
            "band_count": lane.band_count_annotated,
            "bbox": lane.bbox,
            # The lane as drawn and hit-tested (Rule 2, spec 2026-10-10 §4): a tilted lane's box takes in its
            # neighbours.
            "outline": outline_of(lane),
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

        # Band data (already prefetched with densitometry, from the top of the lane)
        for rank, band in enumerate(lane.bands.all(), 1):
            band_data = {
                "id": str(band.id),
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                # The band's name on the page ("B3"): analysis_detail.band_number, the reports' rule too.
                "band_number": band_number(band, rank),
                "band_type": band.band_type,
                "detection_source": band.detection_source,
                "position_y": band.position_y,
                "estimated_mw_kda": band.estimated_mw_kda,
                "bbox": band.bbox,
                # Its part in the lane's western readout (aggregate / main / clipping, hcp / left_out),
                # or None: the server's classification, never the browser's (spec I2).
                "role": roles.get(str(band.id)),
            }

            # Add densitometry if available (already prefetched)
            try:
                densitometry = band.densitometry
                band_data["densitometry"] = {
                    "corrected_area": densitometry.corrected_area,
                    "relative_percent_lane": densitometry.relative_percent_lane,
                    "fit_r_squared": densitometry.fit_r_squared,
                    "saturated_pixel_fraction": densitometry.saturated_pixel_fraction,
                    "saturated": densitometry.saturated,
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
            "mw_range": (
                {
                    "min": (
                        float(calibration.template.mw_range_min)
                        if calibration.template and calibration.template.mw_range_min
                        else None
                    ),
                    "max": (
                        float(calibration.template.mw_range_max)
                        if calibration.template and calibration.template.mw_range_max
                        else None
                    ),
                }
                if calibration.template
                else None
            ),
        }

    # Get available ladder templates for MW axis
    ladder_templates = list(LadderTemplate.objects.filter(is_active=True).values("id", "name", "manufacturer"))

    # Build lane IDs CSV for comparison link
    lane_ids_csv = ",".join(str(lane["id"]) for lane in lanes)

    # Western readout (spec §4.4): the header select is server-rendered so it works before any
    # densitometry run; the JS reads the same facts from readout_config_json until its first fetch.
    readout_assay = assay_summary(analysis)
    can_write = user_can_write_gel_analyzer(request.user)
    # Why Run Analysis and Save & apply are greyed out, or None. The server refuses both on the same
    # rules: write access first (access.py), then an approved analysis (services/analysis_status.py).
    if not can_write:
        run_locked_reason = "You need write access to Gel Analyzer to run densitometry"
        quant_locked_reason = "You need write access to Gel Analyzer to save the quantification."
    elif is_final(analysis):
        run_locked_reason = "Approved analyses are final: densitometry cannot be re-run"
        quant_locked_reason = "Approved analyses are final: the quantification cannot be saved."
    else:
        run_locked_reason = quant_locked_reason = None

    readout_config = {
        "assay": readout_assay,
        "can_write": can_write,
        "is_editable": analysis.is_editable,
        "reference_lane_id": analysis.readout_reference_lane_id,
    }

    context = {
        "analysis": analysis,
        "gel_image": analysis.gel_image,
        # Serialize as JSON to handle None -> null conversion for JavaScript
        "lanes": script_json(lanes),
        "bands": script_json(bands),
        "has_results": has_results,
        "calibration_json": script_json(calibration_data),
        "ladder_templates": ladder_templates,
        "lane_count": len(lanes),
        "band_count": len(bands),
        "lane_ids_csv": lane_ids_csv,
        "readout_assay": readout_assay,
        "can_write": can_write,
        "readout_reference_lane_id": analysis.readout_reference_lane_id,
        "reference_candidates": reference_candidates,
        "readout_config_json": script_json(readout_config),
        "run_locked_reason": run_locked_reason,
        # The page summary (cards, checks, status hint, lane values) the header strip and the
        # Lanes view render; the dict itself for the tests.
        "summary": gel_summary,
        "summary_json": script_json(summary_payload(analysis, gel_summary, lanes_list)),
        "readout": gel_summary["readout"],
        "readout_label": gel_summary["readout_label"],
        "readout_texts": {"MOLECULE_VARIANTS": VARIANT_TEXTS, "HOST_CELL_PROTEINS": HCP_TEXTS}.get(
            gel_summary["readout"], ()
        ),
        "approved_is_final": APPROVED_IS_FINAL,
        "quant_locked_reason": quant_locked_reason,
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
