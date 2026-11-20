"""
One comparison item per lane, for every door of the gel comparison.

The comparison page (``?comparison=``, ``?lanes=``, ``?samples=``), the "Add Sample" wizard
(``api_lane_comparison_data``), the resolve endpoint and the PD dashboard gel slots
(``resolve_samples_to_items``) all build a lane's item with :func:`lane_item` -- the wizard used to keep
a hand copy that had drifted (no purity, no condition, no load).

:func:`enrich` then adds what the page reads the lane FOR, from the gel's own rules
(``services/analysis_detail.py``): its assay and the kind it is compared in, and its readout cells.
Only the comparison page and the wizard call it; the PD gel slots do not pay for it.
"""

from django.urls import reverse

from gel_analyzer.models import GelAnalysis
from gel_analyzer.services.lane_geometry.shape import outline_of
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

# Why a lane cannot be compared, by issue code. Only the first two are critical.
COMPARABILITY_MESSAGES = {
    "no_lane": "Lane data is missing (source analysis may have been deleted)",
    "no_gel_image": "Gel image is not available",
    "no_profile": "Profile data has not been computed",
    "no_calibration": "MW calibration is not available",
}
CRITICAL_ISSUES = ("no_lane", "no_gel_image")


def comparability_message(issues: list) -> str:
    """A user-facing sentence for the comparability issue codes."""
    if not issues:
        return ""
    return ". ".join(COMPARABILITY_MESSAGES.get(issue, f"Unknown issue: {issue}") for issue in issues)


def lane_item(lane, process_sample=None):
    """
    The comparison item of ``lane``: its geometry, bands, profile, calibration and sample.

    ``lane`` comes with ``analysis__gel_image``, ``densitometry_summary`` and its process sample's step
    and sheet selected, ``bands__densitometry`` and ``analysis__ladder_calibrations__template``
    prefetched (the callers' querysets). ``process_sample``: the lane's ProcessSample when the
    comparison names it.

    The id is the LANE's (``lane_<pk>``): a sample's two lanes -- reduced and non-reduced, or its
    SDS-PAGE and its anti-HCP lane -- shared ``process_sample_<pk>`` and the browser dropped the second.
    """
    comparability_issues = []

    if not lane:
        return {
            "lane": None,
            "comparability": {
                "is_valid": False,
                "issues": ["no_lane"],
                "critical_issues": ["no_lane"],
                "message": comparability_message(["no_lane"]),
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

    # Get calibration data for MW estimation.
    # Use the prefetched ladder_calibrations (template comes along via the
    # `analysis__ladder_calibrations__template` chain set by the callers).
    # Avoid `.select_related().first()` here — that invalidates the prefetch
    # cache and adds an extra query per lane.
    calibration = None
    calibration_data = None
    if lane.analysis:
        try:
            cached_calibrations = list(lane.analysis.ladder_calibrations.all())
            calibration = cached_calibrations[0] if cached_calibrations else None
            if calibration:
                template = calibration.template
                calibration_data = {
                    "method": calibration.method,
                    "coefficients": calibration.coefficients,
                    "r_squared": float(calibration.r_squared) if calibration.r_squared else None,
                    "template_name": template.name if template else None,
                    "mw_range": (
                        {
                            "min": (float(template.mw_range_min) if template.mw_range_min else None),
                            "max": (float(template.mw_range_max) if template.mw_range_max else None),
                        }
                        if template
                        else None
                    ),
                }
        except Exception:
            pass

    if not calibration_data:
        comparability_issues.append("no_calibration")

    # Pre-compute MW values for profile if calibration and profile data available.
    # Reuse the `calibration` object resolved above — no extra query.
    mw_profile_data = None
    if profile_data and calibration_data and calibration:
        try:
            y_positions = profile_data.get("y_positions", [])
            intensities = profile_data.get("intensities", [])
            lane_top = lane.y
            lane_bottom = lane.y + lane.height

            if y_positions and intensities and lane_bottom > lane_top:
                mw_values = []
                for y_pos in y_positions:
                    mw = calibration.estimate_mw(int(y_pos), lane_top, lane_bottom)
                    mw_values.append(float(mw) if mw else None)

                mw_profile_data = {
                    "mw_values": mw_values,
                    "intensities": intensities,
                    "y_positions": y_positions,
                }
        except Exception:
            pass

    # Use prefetched bands (densitometry joined via `bands__densitometry`
    # prefetch chain). Sort in Python — calling `.order_by()` on the manager
    # would discard the cache and trigger an extra query per lane.
    bands_data = []
    cached_bands = list(lane.bands.all())
    cached_bands.sort(key=lambda b: b.position_y if b.position_y is not None else 0)
    for band in cached_bands:
        band_data = {
            "id": str(band.pk),
            "band_type": band.band_type,
            "band_type_display": (
                band.get_band_type_display() if hasattr(band, "get_band_type_display") else band.band_type
            ),
            "position_y": float(band.position_y) if band.position_y else None,
            "estimated_mw_kda": (
                float(band.estimated_mw_kda) if hasattr(band, "estimated_mw_kda") and band.estimated_mw_kda else None
            ),
            "bbox": (
                band.bbox
                if band.bbox
                else {
                    "x": band.bbox_x if hasattr(band, "bbox_x") else None,
                    "y": band.bbox_y if hasattr(band, "bbox_y") else None,
                    "width": band.bbox_width if hasattr(band, "bbox_width") else None,
                    "height": band.bbox_height if hasattr(band, "bbox_height") else None,
                }
            ),
        }

        # Add densitometry data if available (the union of what the page and the wizard used to send)
        if hasattr(band, "densitometry") and band.densitometry:
            densitometry = band.densitometry
            band_data["densitometry"] = {
                "corrected_area": float(densitometry.corrected_area) if densitometry.corrected_area else None,
                "relative_percent_lane": (
                    float(densitometry.relative_percent_lane) if densitometry.relative_percent_lane else None
                ),
                "relative_percent_gel": (
                    float(densitometry.relative_percent_gel) if densitometry.relative_percent_gel else None
                ),
                "fit_r_squared": float(densitometry.fit_r_squared) if densitometry.fit_r_squared else None,
                "peak_amplitude": float(densitometry.peak_amplitude) if densitometry.peak_amplitude else None,
                "fwhm": float(densitometry.fwhm) if densitometry.fwhm else None,
            }

        bands_data.append(band_data)

    # Build comparability status - only flag critical issues (no_lane, no_gel_image)
    critical_issues = [i for i in comparability_issues if i in CRITICAL_ISSUES]

    # Build label based on source
    if process_sample:
        label = process_sample.sample_id
        source = "process_sample"
    elif lane.sample_name:
        label = f"Lane {lane.lane_number}: {lane.sample_name}"
        source = "lane"
    else:
        label = f"Lane {lane.lane_number}"
        source = "lane"

    return {
        "id": f"lane_{lane.pk}",
        "source": source,
        "label": label,
        "cdw_batch_id": (process_sample.cdw_batch_id or "") if process_sample else "",
        "sample": (
            {
                "id": process_sample.pk if process_sample else None,
                "sample_id": process_sample.sample_id if process_sample else None,
                "step_name": (
                    process_sample.step_execution.step_template.name
                    if process_sample and process_sample.step_execution and process_sample.step_execution.step_template
                    else None
                ),
                "sheet_number": (
                    process_sample.step_execution.process_sheet.sheet_number
                    if process_sample and process_sample.step_execution and process_sample.step_execution.process_sheet
                    else None
                ),
            }
            if process_sample
            else None
        ),
        "lane": {
            "id": lane.pk,
            "lane_number": lane.lane_number,
            "sample_name": lane.sample_name or None,
            "process_sample_id": lane.process_sample_id if hasattr(lane, "process_sample_id") else None,
            "is_reduced": lane.is_reduced if hasattr(lane, "is_reduced") else None,
            "protein_load_ug": (
                float(lane.protein_load_ug) if hasattr(lane, "protein_load_ug") and lane.protein_load_ug else None
            ),
            "protein_load_type": (
                lane.get_protein_load_type_display()
                if hasattr(lane, "protein_load_type") and lane.protein_load_type
                else None
            ),
            "bbox": {
                "x": lane.x,
                "y": lane.y,
                "width": lane.width,
                "height": lane.height,
            },
            # The lane as drawn, hit-tested and cropped (Rule 2, spec 2026-10-10 §4).
            "outline": outline_of(lane),
        },
        "lane_geometry": {
            "top": lane.y,
            "bottom": lane.y + lane.height,
        },
        "image_url": image_url,
        "profile": profile_data,
        "mw_profile": mw_profile_data,
        "calibration": calibration_data,
        "analysis": (
            {
                "id": str(lane.analysis.pk) if lane.analysis else None,
                "name": lane.analysis.name if lane.analysis else None,
                "gel_type": lane.analysis.gel_image.gel_type if lane.analysis and lane.analysis.gel_image else None,
            }
            if lane.analysis
            else None
        ),
        "bands": bands_data,
        "densitometry": {
            "poi_percentage": (
                float(lane.densitometry_summary.poi_percentage)
                if hasattr(lane, "densitometry_summary")
                and lane.densitometry_summary
                and lane.densitometry_summary.poi_percentage is not None
                else None
            ),
        },
        "comparability": {
            "is_valid": len(critical_issues) == 0,
            "issues": comparability_issues,
            "critical_issues": critical_issues,
            "message": comparability_message(critical_issues) if critical_issues else None,
        },
    }


def kind_key(gel_image) -> str:
    """The kind a lane is compared in: one assay, keyed by its NAME (owner, 2026-10-11 and 2026-10-12).

    An image with no assay joins "SDS-PAGE" when it measures purity -- the PD sample comparison's rule
    (``scmp-gel.js::kindOf``): a legacy purity gel is an SDS-PAGE -- else it is its own kind,
    "<gel type> · no assay". Lanes of two kinds are never drawn on one axis.
    """
    from gel_analyzer.services.analysis_detail import assay_label
    from gel_analyzer.signals import image_measures_purity

    if gel_image.assay_id is not None:
        return gel_image.assay.name
    if image_measures_purity(gel_image):
        return "SDS-PAGE"
    return assay_label(gel_image)


def kind_of(gel_image) -> dict:
    """The lane's kind (:func:`kind_key`) with its readout and the readout's columns."""
    from gel_analyzer.services.analysis_detail import READOUT_LABELS, page_readout, readout_columns

    key = kind_key(gel_image)
    readout = page_readout(gel_image)
    return {
        "key": key,
        "label": key,
        "readout": readout,
        "readout_label": READOUT_LABELS[readout],
        # The comparison reads the readout, not the quantification: no Measured column.
        "columns": readout_columns(readout, has_quant=False),
    }


def enrich(items) -> None:
    """Add to each item (in place) its assay, kind, readout and the link to its analysis.

    One pass for the page: the items' analyses are loaded once with their lanes whole
    (``summary_lanes_prefetch``), ``lane_readouts`` reads that prefetch, and ``lane_rows`` gives the
    analysis page's own cells for the page's lanes -- the comparison never computes a readout.
    ``readout.carries``: whether the lane carries the gel's readout at all (a ladder, or a control
    lane that is not the HCP reference on a western, carries none and shows "—", never a reason that
    belongs to another lane).
    """
    from gel_analyzer.models import GelAssay
    from gel_analyzer.services.analysis_detail import lane_rows, payload_row, summary_lanes_prefetch
    from gel_analyzer.services.readout_publisher import lane_readouts
    from gel_analyzer.services.sample_gels import lane_strip_entries
    from gel_analyzer.signals import lane_publishes_purity

    analysis_ids = {item["analysis"]["id"] for item in items if item.get("analysis") and item["analysis"].get("id")}
    if not analysis_ids:
        return
    analyses = {
        str(analysis.pk): analysis
        for analysis in GelAnalysis.objects.filter(pk__in=analysis_ids)
        .select_related("gel_image__assay", "readout_reference_lane")
        .prefetch_related(summary_lanes_prefetch())
    }

    rows_by_lane = {}
    kinds = {}
    page_lanes = []
    for analysis_id, analysis in analyses.items():
        kind = kind_of(analysis.gel_image)
        kinds[analysis_id] = kind
        readout = kind["readout"]
        page_lane_ids = {
            item["lane"]["id"] for item in items if item.get("lane") and item["analysis"]["id"] == analysis_id
        }
        lanes = [lane for lane in analysis.lanes.all() if lane.pk in page_lane_ids]
        page_lanes.extend(lanes)
        readouts = lane_readouts(analysis) if readout in GelAssay.WESTERN_READOUTS else None
        measured = [column["key"] for column in kind["columns"] if column["key"] not in ("bands", "poi_kda")]
        reference = analysis.readout_reference_lane
        for lane, row in zip(
            lanes, lane_rows(analysis, lanes, readout, has_quant=False, readouts=readouts), strict=False
        ):
            publishes = lane_publishes_purity(lane) if readout == GelAssay.Readout.PURITY else False
            payload = payload_row(row, readout, publishes)
            payload["values"] = row["values"] or {}
            payload["carries"] = any(key in row["cells"] for key in measured)
            payload["reference_lane_number"] = (
                reference.lane_number
                if reference is not None and readout == GelAssay.Readout.HOST_CELL_PROTEINS
                else None
            )
            rows_by_lane[lane.pk] = payload

    # The lanes side by side on a common kDa axis (js/viz/lane-strips.js): the PD sample comparison's
    # entry; its profile is the item's own (no second copy in the page).
    strips = lane_strip_entries(page_lanes)
    for strip in strips.values():
        strip["profile"] = None

    for item in items:
        analysis_id = (item.get("analysis") or {}).get("id")
        analysis = analyses.get(analysis_id)
        if analysis is None or not item.get("lane"):
            continue
        image = analysis.gel_image
        item["assay"] = {"name": image.assay.name, "readout": image.assay.readout} if image.assay_id else None
        item["gel_type"] = image.get_gel_type_display()
        item["kind"] = kinds[analysis_id]
        item["readout"] = rows_by_lane.get(item["lane"]["id"])
        item["strip"] = strips.get(item["lane"]["id"])
        item["analysis"]["url"] = reverse("gel_analyzer:analysis_detail", kwargs={"pk": analysis.pk})
        item["analysis"]["status"] = analysis.get_status_display()
