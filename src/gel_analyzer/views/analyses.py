"""Analysis HTML views.

Provides:
- analysis_list_view: List all analyses with filtering (Phase 3)
- analysis_create_view: Create new analysis for an image (Phase 3)
- analysis_detail_view: View analysis details — read-only (Phase 4)
- analysis_annotate_view: Interactive annotation editor (Phase 4)

ProcessSample / sample_analyses references already removed in Phase 2's
models — heavy views ported from `$DSHUB/gel_analyzer/views/analyses.py`
with `lane.process_sample` lookups stripped.
"""

from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe

from gel_analyzer.forms.analysis_forms import GelAnalysisCreateForm, lane_to_dict
from gel_analyzer.models import GelAnalysis, GelImage
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper Functions for Analysis Context
# =============================================================================


def _r_squared_quality(r_squared):
    """Return quality label for R² value."""
    if r_squared is None:
        return "unknown"
    if r_squared >= 0.99:
        return "excellent"
    if r_squared >= 0.95:
        return "good"
    if r_squared >= 0.90:
        return "acceptable"
    return "poor"


def _get_calibration_info(analysis):
    """
    Get calibration status and details for context display.

    Returns dict with:
    - status: 'calibrated' or 'not_calibrated'
    - ladder_count: number of calibrated ladders
    - best_r_squared: highest R² value
    - r_squared_quality: 'excellent', 'good', 'acceptable', 'poor'
    - template_name: ladder template name
    """
    calibrations = list(analysis.ladder_calibrations.all())

    if not calibrations:
        return {
            "status": "not_calibrated",
            "message": "No MW calibration performed",
        }

    # Find best R² among all calibrations
    r_squared_values = [c.r_squared for c in calibrations if c.r_squared is not None]
    best_r2 = max(r_squared_values) if r_squared_values else None

    # Get template name from first calibration
    template_name = None
    for c in calibrations:
        if c.template:
            template_name = c.template.name
            break

    return {
        "status": "calibrated",
        "ladder_count": len(calibrations),
        "best_r_squared": best_r2,
        "r_squared_quality": _r_squared_quality(best_r2),
        "template_name": template_name,
    }


def _get_densitometry_info(analysis, lanes):
    """
    Get densitometry summary for context display.

    Returns dict with:
    - has_results: whether any densitometry results exist
    - lanes: list of lane results with purity
    - average_purity: average POI purity across sample lanes
    """
    results = []
    total_poi_purity = []

    for lane in lanes:
        # Check if lane has densitometry summary
        try:
            summary = lane.densitometry_summary
        except Exception:
            continue

        if lane.lane_type == "SAMPLE" and summary:
            sample_name = lane.sample_name

            results.append(
                {
                    "lane_number": lane.lane_number,
                    "sample_name": sample_name,
                    "poi_percentage": summary.poi_percentage,
                    "band_count": summary.band_count,
                }
            )

            if summary.poi_percentage is not None:
                total_poi_purity.append(summary.poi_percentage)

    return {
        "has_results": bool(results),
        "lanes": results,
        "average_purity": sum(total_poi_purity) / len(total_poi_purity) if total_poi_purity else None,
    }


def _get_completion_info(analysis, lanes):
    """
    Check completion status of analysis workflow.

    Returns dict with boolean flags for each step:
    - has_lanes
    - has_bands
    - has_calibration
    - has_densitometry
    - has_poi (at least one POI band identified)
    """
    has_poi = False
    has_densitometry = False

    for lane in lanes:
        # Check for POI bands
        for band in lane.bands.all():
            if band.band_type == "POI":
                has_poi = True
                break

        # Check for densitometry
        try:
            if lane.densitometry_summary:
                has_densitometry = True
        except Exception:
            pass

    return {
        "has_lanes": analysis.total_lanes > 0,
        "has_bands": analysis.total_bands > 0,
        "has_calibration": analysis.ladder_calibrations.exists(),
        "has_densitometry": has_densitometry,
        "has_poi": has_poi,
    }


def _get_warnings(analysis, lanes):
    """
    Generate warnings for missing data.

    Returns list of warning dicts with:
    - type: warning category
    - lane: lane number (if applicable)
    - message: human-readable message
    """
    warnings = []

    # Check each sample lane
    for lane in lanes:
        if lane.lane_type == "SAMPLE":
            # Check for missing sample identification
            if not lane.sample_name:
                warnings.append(
                    {
                        "type": "missing_sample",
                        "lane": lane.lane_number,
                        "message": f"Lane {lane.lane_number}: No sample name set",
                    }
                )

            # Check for missing POI
            poi_bands = [b for b in lane.bands.all() if b.band_type == "POI"]
            if not poi_bands:
                warnings.append(
                    {
                        "type": "missing_poi",
                        "lane": lane.lane_number,
                        "message": f"Lane {lane.lane_number}: No POI band identified",
                    }
                )

    # Check for calibration
    if analysis.total_lanes > 0 and not analysis.ladder_calibrations.exists():
        ladder_lanes = [lane for lane in lanes if lane.lane_type == "LADDER"]
        if ladder_lanes:
            warnings.append(
                {
                    "type": "no_calibration",
                    "message": "MW calibration not performed (ladder lanes exist)",
                }
            )

    # Sort by type for proper grouping in template (required for {% regroup %})
    return sorted(warnings, key=lambda w: w["type"])


@login_required
def analysis_list_view(request: HttpRequest) -> HttpResponse:
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "")

    analyses = GelAnalysis.objects.select_related("gel_image", "created_by").order_by("-created_at")
    if status_filter:
        analyses = analyses.filter(status=status_filter)
    if search_query:
        analyses = analyses.filter(
            Q(name__icontains=search_query) | Q(gel_image__original_filename__icontains=search_query)
        )

    paginator = Paginator(analyses, 24)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "gel_analyzer/analyses/list.html",
        {
            "page_obj": page_obj,
            "analyses": page_obj.object_list,
            "status_filter": status_filter,
            "search_query": search_query,
            "status_choices": GelAnalysis.Status.choices,
        },
    )


@login_required
def analysis_create_view(request: HttpRequest, image_pk) -> HttpResponse:
    gel_image = get_object_or_404(GelImage, pk=image_pk)

    if request.method == "POST":
        form = GelAnalysisCreateForm(request.POST)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.gel_image = gel_image
            analysis.created_by = request.user
            analysis.save()
            logger.info(
                f"Created GelAnalysis {analysis.id}",
                user=request.user.username,
                gel_image_id=str(gel_image.id),
            )
            messages.success(request, "Analysis created — start annotating below.")
            return redirect("gel_analyzer:analysis_annotate", pk=analysis.id)
    else:
        form = GelAnalysisCreateForm(initial={"name": gel_image.original_filename})

    return render(
        request,
        "gel_analyzer/analyses/create.html",
        {"gel_image": gel_image, "form": form},
    )


@login_required
def analysis_detail_view(request: HttpRequest, pk) -> HttpResponse:
    """
    View analysis details in read-only mode.

    Displays:
    - Annotated gel image with SVG overlay
    - Context cards (calibration, densitometry, completion)
    - Workflow progress indicator
    - Warnings for missing data
    - Lane accordion with sample info and purity
    """
    # Optimized query with related data for context
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related(
            "gel_image", "created_by", "approved_by", "multi_ladder_config__template"
        ).prefetch_related(
            "ladder_calibrations__ladder_lane",
            "ladder_calibrations__template",
        ),
        pk=pk,
    )

    # Get lanes with optimized related data
    lanes = (
        analysis.lanes.select_related(
            "ladder_template",
        )
        .prefetch_related("bands")
        .order_by("lane_number")
    )

    # Convert to list for multiple iterations in helper functions
    lanes_list = list(lanes)

    # Get context data for display
    calibration_info = _get_calibration_info(analysis)
    densitometry_info = _get_densitometry_info(analysis, lanes_list)
    completion_info = _get_completion_info(analysis, lanes_list)
    warnings = _get_warnings(analysis, lanes_list)

    # Serialize lanes for JavaScript (SVG renderer + spreadsheet).
    # Augment each dict with derived read-only stats so the spreadsheet
    # can display POI kDa / purity / band count without re-fetching.
    densitometry_by_lane = {d["lane_number"]: d for d in densitometry_info.get("lanes", [])}
    serialized_lanes = []
    for lane in lanes_list:
        lane_dict = lane_to_dict(lane)
        lane_dict["_band_count"] = lane.bands.count()
        poi_kda = None
        for band in lane.bands.all():
            if band.band_type == "POI" and band.estimated_mw_kda:
                poi_kda = float(band.estimated_mw_kda)
                break
        lane_dict["poi_kda"] = poi_kda
        lane_dict["purity"] = densitometry_by_lane.get(lane.lane_number, {}).get("poi_percentage")
        serialized_lanes.append(lane_dict)
    lanes_json = mark_safe(json.dumps(serialized_lanes))

    # Pre-compute lane data for card/table views
    lane_data = []
    densitometry_by_lane = {d["lane_number"]: d for d in densitometry_info.get("lanes", [])}
    for lane in lanes_list:
        if lane.lane_type not in ("SAMPLE", "CONTROL"):
            continue
        band_count = lane.bands.count()
        poi_kda = None
        for band in lane.bands.all():
            if band.band_type == "POI" and band.estimated_mw_kda:
                poi_kda = band.estimated_mw_kda
                break
        densitometry_lane = densitometry_by_lane.get(lane.lane_number, {})
        purity = densitometry_lane.get("poi_percentage")

        sample_display = lane.sample_name

        lane_data.append(
            {
                "lane": lane,
                "band_count": band_count,
                "poi_kda": poi_kda,
                "purity": purity,
                "sample_display": sample_display,
                "has_sample": bool(lane.sample_name),
            }
        )

    # Can edit samples if analysis is in an editable status
    can_edit_samples = analysis.is_editable

    # Check if user is QA (for approval workflow buttons)
    user_is_qa = request.user.is_staff or request.user.groups.filter(name="Gel QA Team").exists()

    context = {
        "page_title": analysis.name,
        "analysis": analysis,
        "lanes": lanes_list,
        "lanes_json": lanes_json,
        "lane_data": lane_data,
        "can_edit_samples": can_edit_samples,
        "user_is_qa": user_is_qa,
        "image_width": analysis.gel_image.width,
        "image_height": analysis.gel_image.height,
        # Context data
        "calibration_info": calibration_info,
        "densitometry_info": densitometry_info,
        "completion_info": completion_info,
        "warnings": warnings,
    }

    return render(request, "gel_analyzer/analyses/detail.html", context)


@login_required
def analysis_annotate_view(request: HttpRequest, pk) -> HttpResponse:
    """
    Interactive annotation editor for an analysis.

    This is the main annotation view with:
    - Image viewer with pan/zoom
    - SVG overlay for annotations
    - Toolbar for tools (select, lane, band)
    - Properties panel for selected items
    """
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image"),
        pk=pk,
    )

    # Check if analysis is editable
    if not analysis.is_editable:
        messages.warning(
            request,
            "This analysis is no longer editable. View it in read-only mode.",
        )
        return redirect("gel_analyzer:analysis_detail", pk=pk)

    # Update status to IN_PROGRESS if still DRAFT
    if analysis.status == "DRAFT":
        analysis.status = "IN_PROGRESS"
        analysis.save(update_fields=["status"])

    context = {
        "page_title": f"Annotate: {analysis.name}",
        "analysis": analysis,
        "gel_image": analysis.gel_image,
    }

    # Use standalone template (Bootstrap-free) for better control
    return render(request, "gel_analyzer/analyses/annotate_standalone.html", context)
