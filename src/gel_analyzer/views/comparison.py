"""
Sample Comparison views for gel_analyzer.

Provides views for comparing gel densitometry results across multiple lanes.
Supports two entry modes:
- Lane mode: ?lanes=123,456,789 (Lane IDs directly from gel_analyzer)
- Saved comparison: ?comparison=<uuid>

ProcessSample integration was removed in Phoresis (Phase 2): per-lane sample
metadata now lives on `Lane.sample_metadata` (JSON) and `Lane.sample_name`.
"""

import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse

from gel_analyzer.models import GelAnalysis, GelImage, Lane, SavedComparison
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _get_comparability_message(issues: list) -> str:
    """
    Generate a user-friendly message for comparability issues.

    Args:
        issues: List of issue codes

    Returns:
        Human-readable message explaining why sample/lane cannot be compared
    """
    if not issues:
        return ""

    messages = {
        "no_lane": "Lane data is missing (source analysis may have been deleted)",
        "no_gel_image": "Gel image is not available",
        "no_profile": "Profile data has not been computed",
        "no_calibration": "MW calibration is not available",
    }

    parts = [messages.get(issue, f"Unknown issue: {issue}") for issue in issues]
    return ". ".join(parts)


def _serialize_lane_data(lane):
    """
    Serialize lane data for comparison view.

    Args:
        lane: Lane object

    Returns:
        dict: Serialized lane data for JavaScript consumption
    """
    comparability_issues = []

    if not lane:
        comparability_issues.append("no_lane")
        return {
            "lane": None,
            "comparability": {
                "is_valid": False,
                "issues": ["no_lane"],
                "critical_issues": ["no_lane"],
                "message": _get_comparability_message(["no_lane"]),
            },
        }

    # Get gel image URL via proxy to avoid CORS issues with Azure Blob Storage
    image_url = None
    gel_image = None

    try:
        if lane.analysis and lane.analysis.gel_image:
            gel_image = lane.analysis.gel_image
            image_url = reverse("gel_analyzer:api_image_proxy", kwargs={"pk": gel_image.pk})
    except Exception as e:
        logger.warning(f"Error getting gel image URL for lane {lane.pk}: {e}")

    if not image_url:
        comparability_issues.append("no_gel_image")

    # Get profile data from LaneDensitometrySummary
    profile_data = None
    if hasattr(lane, "densitometry_summary") and lane.densitometry_summary:
        try:
            summary = lane.densitometry_summary
            if summary.profile_data:
                profile_data = summary.profile_data
        except Exception:
            pass

    if not profile_data:
        comparability_issues.append("no_profile")

    # Get calibration data for MW estimation
    calibration_data = None
    if lane.analysis:
        try:
            calibration = lane.analysis.ladder_calibrations.select_related("template").first()
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
        except Exception:
            pass

    if not calibration_data:
        comparability_issues.append("no_calibration")

    # Pre-compute MW values for profile if calibration and profile data available.
    # Rf is computed in the LADDER lane's reference frame, not the sample's —
    # see services/calibration/service.py for rationale.
    mw_profile_data = None
    if profile_data and calibration_data:
        try:
            y_positions = profile_data.get("y_positions", [])
            intensities = profile_data.get("intensities", [])
            calibration = lane.analysis.ladder_calibrations.first()

            if y_positions and intensities and calibration and calibration.ladder_lane:
                ladder_top = calibration.ladder_lane.y
                ladder_bottom = calibration.ladder_lane.y + calibration.ladder_lane.height
                if ladder_bottom > ladder_top:
                    mw_values = []
                    for y_pos in y_positions:
                        mw = calibration.estimate_mw(int(y_pos), ladder_top, ladder_bottom)
                        mw_values.append(float(mw) if mw else None)

                    mw_profile_data = {
                        "mw_values": mw_values,
                        "intensities": intensities,
                        "y_positions": y_positions,
                    }
        except Exception:
            pass

    # Get bands with densitometry
    bands_data = []
    for band in lane.bands.select_related("densitometry").all().order_by("position_y"):
        band_data = {
            "id": str(band.pk),
            "band_type": band.band_type,
            "band_type_display": band.get_band_type_display()
            if hasattr(band, "get_band_type_display")
            else band.band_type,
            "position_y": float(band.position_y) if band.position_y else None,
            "estimated_mw_kda": float(band.estimated_mw_kda)
            if hasattr(band, "estimated_mw_kda") and band.estimated_mw_kda
            else None,
            "bbox": band.bbox
            if band.bbox
            else {
                "x": band.bbox_x if hasattr(band, "bbox_x") else None,
                "y": band.bbox_y if hasattr(band, "bbox_y") else None,
                "width": band.bbox_width if hasattr(band, "bbox_width") else None,
                "height": band.bbox_height if hasattr(band, "bbox_height") else None,
            },
        }

        # Add densitometry data if available
        if hasattr(band, "densitometry") and band.densitometry:
            densitometry = band.densitometry
            band_data["densitometry"] = {
                "corrected_area": float(densitometry.corrected_area) if densitometry.corrected_area else None,
                "relative_percent_lane": float(densitometry.relative_percent_lane)
                if densitometry.relative_percent_lane
                else None,
                "fit_r_squared": float(densitometry.fit_r_squared) if densitometry.fit_r_squared else None,
                "peak_amplitude": float(densitometry.peak_amplitude) if densitometry.peak_amplitude else None,
            }

        bands_data.append(band_data)

    # Build comparability status - only flag critical issues (no_lane, no_gel_image)
    critical_issues = [i for i in comparability_issues if i in ("no_lane", "no_gel_image")]

    # Build label based on lane sample info
    label = f"Lane {lane.lane_number}: {lane.sample_name}" if lane.sample_name else f"Lane {lane.lane_number}"
    source = "lane"
    source_id = lane.pk

    return {
        "id": f"{source}_{source_id}",
        "source": source,
        "label": label,
        "sample": None,
        "lane": {
            "id": lane.pk,
            "lane_number": lane.lane_number,
            "sample_name": lane.sample_name or None,
            "sample_metadata": lane.sample_metadata or {},
            "is_reduced": lane.is_reduced if hasattr(lane, "is_reduced") else None,
            "protein_load_ug": float(lane.protein_load_ug)
            if hasattr(lane, "protein_load_ug") and lane.protein_load_ug
            else None,
            "protein_load_type": lane.get_protein_load_type_display()
            if hasattr(lane, "protein_load_type") and lane.protein_load_type
            else None,
            "bbox": {
                "x": lane.x,
                "y": lane.y,
                "width": lane.width,
                "height": lane.height,
            },
        },
        "lane_geometry": {
            "top": lane.y,
            "bottom": lane.y + lane.height,
        },
        "image_url": image_url,
        "profile": profile_data,
        "mw_profile": mw_profile_data,
        "calibration": calibration_data,
        "analysis": {
            "id": str(lane.analysis.pk) if lane.analysis else None,
            "name": lane.analysis.name if lane.analysis else None,
            "gel_type": lane.analysis.gel_image.gel_type if lane.analysis and lane.analysis.gel_image else None,
        }
        if lane.analysis
        else None,
        "bands": bands_data,
        "densitometry": {
            "poi_percentage": float(lane.densitometry_summary.poi_percentage)
            if hasattr(lane, "densitometry_summary")
            and lane.densitometry_summary
            and lane.densitometry_summary.poi_percentage is not None
            else None,
        },
        "comparability": {
            "is_valid": len(critical_issues) == 0,
            "issues": comparability_issues,
            "critical_issues": critical_issues,
            "message": _get_comparability_message(critical_issues) if critical_issues else None,
        },
    }


@login_required
def comparison_list_view(request):
    """
    Landing page for sample/lane comparison feature.

    Shows:
    - Saved comparisons (user's own + public) as cards
    - "Start New Comparison" button
    - Recent analyses with densitometry data
    - Quick access filters
    """
    # Get saved comparisons for current user + public
    saved_comparisons = (
        SavedComparison.objects.filter(Q(created_by=request.user) | Q(is_public=True))
        .select_related("created_by")
        .prefetch_related("savedcomparisonlane_set__lane__analysis__gel_image")
        .order_by("-updated_at")[:20]
    )

    # Get recent analyses with completed densitometry
    recent_analyses = (
        GelAnalysis.objects.filter(lanes__densitometry_summary__isnull=False)
        .select_related("gel_image")
        .distinct()
        .order_by("-created_at")[:20]
    )

    # Get available gel images for filtering
    available_images = (
        GelImage.objects.filter(analyses__lanes__densitometry_summary__isnull=False)
        .distinct()
        .order_by("-uploaded_at")[:20]
    )

    context = {
        "saved_comparisons": saved_comparisons,
        "recent_analyses": recent_analyses,
        "available_images": available_images,
        "current_user_id": request.user.pk,
    }

    return render(request, "gel_analyzer/comparisons/list.html", context)


@login_required
def sample_comparison_view(request):
    """
    Compare gel densitometry results from multiple lanes.

    Supports two entry modes:
    - ?comparison=<uuid> → Load a saved comparison
    - ?lanes=123,456,789 → Lane IDs directly (gel_analyzer standalone use)
    """
    # Check if loading from a saved comparison
    comparison_id = request.GET.get("comparison")
    saved_comparison = None
    saved_comparison_json = "null"

    if comparison_id:
        try:
            saved_comparison = SavedComparison.objects.get(pk=comparison_id)
            # Access check: owner or public
            if not saved_comparison.is_public and saved_comparison.created_by != request.user:
                saved_comparison = None
        except (SavedComparison.DoesNotExist, ValueError):
            pass

    # Collect all items to compare
    items_data = []

    if saved_comparison:
        # Load lanes from saved comparison in order
        saved_lane_ids = list(
            saved_comparison.savedcomparisonlane_set.order_by("order").values_list("lane_id", flat=True)
        )
        # Feed into lane-mode processing below
        lane_ids_override = [str(lid) for lid in saved_lane_ids]

        saved_comparison_json = json.dumps(
            {
                "id": str(saved_comparison.pk),
                "name": saved_comparison.name,
                "description": saved_comparison.description,
                "is_public": saved_comparison.is_public,
                "view_settings": saved_comparison.view_settings or {},
            }
        )
    else:
        lane_ids_override = None

    # Lane mode (gel_analyzer standalone or saved comparison override)
    lane_ids = lane_ids_override if lane_ids_override else request.GET.getlist("lanes", [])
    remaining_slots = max(0, 20 - len(items_data))  # Generous limit

    for lane_id in lane_ids[:remaining_slots]:
        try:
            lane = (
                Lane.objects.select_related(
                    "analysis__gel_image",
                    "densitometry_summary",
                )
                .prefetch_related(
                    "bands__densitometry",
                    "analysis__ladder_calibrations__template",
                )
                .get(pk=lane_id)
            )

            items_data.append(_serialize_lane_data(lane))

        except Lane.DoesNotExist:
            continue
        except Exception as e:
            logger.error(f"Error processing lane {lane_id}: {e}")
            continue

    items_json = json.dumps(items_data)

    # Get available Lanes with densitometry (for modal - Gel Lanes tab)
    selected_lane_ids = [s["lane"]["id"] for s in items_data if s.get("lane") and s["lane"].get("id")]

    available_lanes_qs = Lane.objects.filter(
        densitometry_summary__isnull=False,
        lane_type=Lane.LaneType.SAMPLE,  # Only sample lanes, not ladder lanes
    ).select_related("analysis__gel_image")

    if selected_lane_ids:
        available_lanes_qs = available_lanes_qs.exclude(pk__in=selected_lane_ids)

    available_lanes = list(available_lanes_qs.order_by("-analysis__created_at")[:50])

    # Get unique analyses for filter dropdown (Gel Lanes tab)
    available_analyses = list(
        GelAnalysis.objects.filter(lanes__densitometry_summary__isnull=False)
        .select_related("gel_image")
        .distinct()
        .values("pk", "name", "gel_image__gel_type")
        .order_by("-created_at")[:20]
    )

    # Get unique gel images for filter dropdown (Gel Lanes tab)
    available_images = list(
        GelImage.objects.filter(analyses__lanes__densitometry_summary__isnull=False)
        .distinct()
        .values("pk", "original_filename")
        .order_by("-uploaded_at")[:20]
    )

    context = {
        "items_data": items_data,
        "items_json": items_json,
        "available_lanes": available_lanes,
        "available_analyses": available_analyses,
        "available_images": available_images,
        "can_add_more": True,
        # Saved comparison context
        "saved_comparison_id": str(saved_comparison.pk) if saved_comparison else "",
        "saved_comparison_name": saved_comparison.name if saved_comparison else "",
        "saved_comparison_json": saved_comparison_json,
        # Support ?back= parameter for return navigation
        "back_url": request.GET.get("back", ""),
    }

    return render(request, "gel_analyzer/comparisons/compare.html", context)
