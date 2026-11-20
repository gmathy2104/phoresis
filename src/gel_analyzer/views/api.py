"""
JSON API endpoints for Gel Analyzer annotations.

Provides CRUD operations for Lanes and Bands used by the annotation viewer.

Endpoints:
- GET/POST /api/analyses/<pk>/lanes/ - List/create lanes
- POST /api/analyses/<pk>/lanes/bulk/ - Bulk create lanes (YOLO detection)
- GET/PUT/DELETE /api/lanes/<pk>/ - Lane detail/update/delete
- POST /api/lanes/<pk>/bands/ - Create band in lane
- GET/PUT/DELETE /api/bands/<pk>/ - Band detail/update/delete
- GET /api/images/<pk>/proxy/ - Image proxy for CORS-free access
"""

import contextlib
import hashlib
import json
import math

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition, require_http_methods

from gel_analyzer.access import user_can_write_gel_analyzer
from gel_analyzer.forms import band_to_dict, lane_to_dict
from gel_analyzer.models import Band, GelAnalysis, GelImage, LadderTemplate, Lane
from gel_analyzer.services.comparison_items import enrich, lane_item
from gel_analyzer.services.lane_geometry.shape import GeometryRefused, normalize_lane_write
from gel_analyzer.services.quantification.band_type_change import BandTypeRefused, apply_band_type, check_band_type
from gel_analyzer.services.quantification.lane_type_change import CalibrationPointsHeld, guard_lane_type_change
from phoresis_core.error_handling.helpers import public_error_text
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

LANE_GEOMETRY_KEYS = ("lane_shape", "polygon", "x", "y", "width", "height")


def json_error(message: str, status: int = 400) -> JsonResponse:
    """Return a JSON error response."""
    return JsonResponse({"error": message}, status=status)


def parse_json_body(request) -> dict | None:
    """Parse JSON body from request. Returns None on decode failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None


def image_size_of(analysis) -> tuple:
    gel = analysis.gel_image
    return (gel.width, gel.height)


def with_lane_geometry(data: dict, lane, image_size: tuple) -> dict:
    """A lane write's payload with the geometry the server stores (spec 2026-10-10 §4, Rule 1): a non-rectangle
    lane's box is its polygon's outer box, a box-only change maps the stored polygon, an unchanged polygon is not
    rewritten. ``lane`` is None on a create. Raises GeometryRefused."""
    stored = None
    if lane is not None:
        stored = {key: getattr(lane, key) for key in LANE_GEOMETRY_KEYS}
    geometry = normalize_lane_write({k: data[k] for k in LANE_GEOMETRY_KEYS if k in data}, stored, image_size)
    return {**{k: v for k, v in data.items() if k not in LANE_GEOMETRY_KEYS}, **geometry}


def loading_volume_refusal(data: dict) -> str | None:
    """Why a lane write's ``loading_volume_ul`` is refused, else None: null or a finite number >= 0, the model's
    MinValueValidator(0), which ``save()`` never runs."""
    value = data.get("loading_volume_ul")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return "loading_volume_ul must be a number >= 0 or null"
    return None


class LadderTemplateRefused(ValueError):
    """A LADDER lane's write names no ladder template."""


def with_ladder_template(data: dict, lane) -> dict:
    """A lane write's payload with the ladder template the server stores: it follows the lane type, as in the editor
    (``PropertiesPanel._followLadderTemplate``). A lane that is not a LADDER after the write has none, whatever the
    payload says: the editor's band auto-promote (POI -> SAMPLE) sends ``lane_type`` alone. A LADDER lane takes the
    ``ladder_template_id`` it is given, null or a template's id. ``lane`` is None on a create. Raises
    LadderTemplateRefused."""
    lane_type = data.get("lane_type", lane.lane_type if lane is not None else Lane.LaneType.SAMPLE)
    if lane_type != Lane.LaneType.LADDER:
        return {**data, "ladder_template_id": None}
    template_id = data.get("ladder_template_id")
    if template_id is None:
        return data
    try:
        known = LadderTemplate.objects.filter(pk=template_id).exists()
    except ValidationError:  # not a UUID
        known = False
    if not known:
        raise LadderTemplateRefused("ladder_template_id must be the id of a ladder template or null")
    return data


def wants_force(request) -> bool:
    """``?force=true``: the caller confirmed that a lane leaving CALIBRATION/CONTROL discards its calibration points."""
    return request.GET.get("force", "").lower() == "true"


def calibration_points_refusal(refusal: CalibrationPointsHeld) -> JsonResponse:
    """The v1 PATCH's 409 (``detail`` + ``dependent_band_ids``), with the ``error`` this module's clients display."""
    return JsonResponse(
        {"error": f"Lane {refusal.lane.lane_number}: {refusal}", **refusal.payload()},
        status=409,
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_lanes(request, pk):
    """
    GET: List all lanes for an analysis with nested bands.
    POST: Create a new lane.
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if request.method == "GET":
        lanes = analysis.lanes.prefetch_related("bands").order_by("lane_number")
        return JsonResponse(
            {
                "analysis_id": str(analysis.pk),
                "lanes": [lane_to_dict(lane) for lane in lanes],
            }
        )

    elif request.method == "POST":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        data = parse_json_body(request)
        if data is None:
            return json_error("Invalid JSON in request body")
        try:
            data = with_lane_geometry(data, None, image_size_of(analysis))
            data = with_ladder_template(data, None)
        except GeometryRefused as exc:
            return json_error(f"Invalid lane geometry: {exc}")
        except LadderTemplateRefused as exc:
            return json_error(str(exc))
        refusal = loading_volume_refusal(data)
        if refusal:
            return json_error(refusal)

        try:
            # Calculate next available lane_number to avoid conflicts
            # Use max + 1 instead of hardcoded 999 to prevent orphaned lane issues
            max_lane = analysis.lanes.aggregate(Max("lane_number"))["lane_number__max"] or 0
            next_lane_number = max_lane + 1

            # Create lane with next available number (will be recalculated by renumber_lanes)
            lane = Lane.objects.create(
                analysis=analysis,
                lane_number=next_lane_number,  # Use next available, will be fixed by renumber_lanes
                lane_type=data.get("lane_type", "SAMPLE"),
                detection_source=data.get("detection_source", "MANUAL"),
                confidence=data.get("confidence"),
                # Shape and geometry
                lane_shape=data.get("lane_shape", "RECTANGLE"),
                x=data.get("x", 0),
                y=data.get("y", 0),
                width=data.get("width", 50),
                height=data.get("height", 100),
                polygon=data.get("polygon"),
                # Sample conditions and load
                is_reduced=data.get("is_reduced"),
                protein_load_ug=data.get("protein_load_ug"),
                loading_volume_ul=data.get("loading_volume_ul"),
                protein_load_type=data.get("protein_load_type", ""),
                # Sample info
                sample_name=data.get("sample_name", ""),
                ladder_template_id=data.get("ladder_template_id"),
                notes=data.get("notes", ""),
            )

            # Renumber lanes based on X position (left to right)
            analysis.renumber_lanes()
            analysis.update_counts()

            # Refetch lane to get updated lane_number
            lane.refresh_from_db()

            logger.info(
                f"Created lane {lane.lane_number}",
                user=request.user.username,
                analysis_id=str(analysis.pk),
                lane_id=lane.pk,
            )

            return JsonResponse(
                {
                    "success": True,
                    "lane": lane_to_dict(lane),
                },
                status=201,
            )

        except Exception as e:
            logger.exception(f"Error creating lane: {e}")
            return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_lane_detail(request, pk):
    """
    GET: Get lane details.
    PUT: Update lane properties. A lane_type leaving CALIBRATION/CONTROL while its bands hold calibration points
         answers the v1 PATCH's 409 unless ?force=true (guard_lane_type_change).
    DELETE: Delete lane and its bands.
    """
    lane = get_object_or_404(Lane.objects.select_related("analysis"), pk=pk)
    analysis = lane.analysis

    if request.method == "GET":
        return JsonResponse({"lane": lane_to_dict(lane)})

    elif request.method == "PUT":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        data = parse_json_body(request)
        if data is None:
            return json_error("Invalid JSON in request body")
        try:
            data = with_lane_geometry(data, lane, image_size_of(analysis))
        except GeometryRefused as exc:
            return json_error(f"Invalid geometry for lane {lane.lane_number}: {exc}")
        refusal = loading_volume_refusal(data)
        if refusal:
            return json_error(f"Lane {lane.lane_number}: {refusal}")

        # Track if X position changed (requires renumbering)
        old_x = lane.x
        x_changed = "x" in data and data["x"] != old_x

        # Update allowed fields (exclude lane_number - managed by renumber_lanes)
        updatable_fields = [
            "lane_type",
            "lane_shape",
            "x",
            "y",
            "width",
            "height",
            "polygon",
            "is_reduced",
            "protein_load_ug",
            "loading_volume_ul",
            "protein_load_type",
            "sample_name",
            "notes",
        ]
        try:
            with transaction.atomic():
                # Before the type is set: the stored type decides whether the lane leaves CALIBRATION/CONTROL.
                if "lane_type" in data:
                    guard_lane_type_change(lane, data["lane_type"], force=wants_force(request))
                data = with_ladder_template(data, lane)
                for field in updatable_fields:
                    if field in data:
                        setattr(lane, field, data[field])

                # The ladder template follows the lane type (with_ladder_template)
                if "ladder_template_id" in data:
                    lane.ladder_template_id = data["ladder_template_id"]

                lane.save()
        except CalibrationPointsHeld as refusal:
            return calibration_points_refusal(refusal)
        except LadderTemplateRefused as exc:
            return json_error(f"Lane {lane.lane_number}: {exc}")

        # Renumber lanes if position changed
        if x_changed:
            analysis.renumber_lanes()
            lane.refresh_from_db()

        logger.info(f"Updated lane {lane.lane_number}", user=request.user.username, lane_id=lane.pk)

        return JsonResponse(
            {
                "success": True,
                "lane": lane_to_dict(lane),
            }
        )

    elif request.method == "DELETE":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        try:
            lane_number = lane.lane_number
            lane.delete()

            # Renumber remaining lanes and update counts
            analysis.renumber_lanes()
            analysis.update_counts()

            logger.info(f"Deleted lane {lane_number}", user=request.user.username, analysis_id=str(analysis.pk))

            # Return updated lanes so client can refresh lane numbers
            updated_lanes = [
                lane_to_dict(lane) for lane in analysis.lanes.prefetch_related("bands").order_by("lane_number")
            ]

            return JsonResponse(
                {
                    "success": True,
                    "lanes": updated_lanes,  # Client should refresh all lane numbers
                }
            )

        except Exception as e:
            logger.exception(f"Error deleting lane: {e}")
            return json_error("An unexpected error occurred. Please try again.", 500)


@login_required
@require_http_methods(["POST"])
def api_lane_bands(request, pk):
    """
    POST: Create a new band in a lane.

    Concurrent re-analyse / band-delete on the same lane can hold cascade
    locks on DensitometryResult, leading to a Postgres deadlock when this
    handler tries to insert a new Band. The deadlock is properly detected
    and aborted by Postgres; we surface it as a 409 with a retry hint so
    the client can re-issue cleanly instead of seeing a generic 500.
    """
    from django.db import OperationalError, transaction

    lane = get_object_or_404(Lane.objects.select_related("analysis"), pk=pk)
    analysis = lane.analysis

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    # Calculate bbox from polygon if provided
    polygon = data.get("polygon", [])
    bbox_x, bbox_y, bbox_width, bbox_height = None, None, None, None

    if polygon and len(polygon) >= 3:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        bbox_x = min(xs)
        bbox_y = min(ys)
        bbox_width = max(xs) - bbox_x
        bbox_height = max(ys) - bbox_y

    # Default band_type based on lane type (LADDER -> MW_REFERENCE, else OTHER)
    default_band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"
    band_type = data.get("band_type", default_band_type)
    # A new band has no calibration point: CALIBRATION is refused, as the v1 PATCH refuses it without one.
    try:
        check_band_type(None, band_type)
    except BandTypeRefused as refusal:
        return json_error(str(refusal))

    # Single retry on deadlock — concurrent re-analyses are rare but real.
    for attempt in (1, 2):
        try:
            with transaction.atomic():
                # Lock the parent lane row first to establish a consistent
                # ordering for every band-mutation path on this lane. Any
                # concurrent re-analyse / band-delete operation that takes
                # the same lock will queue cleanly behind us instead of
                # interleaving with our cascade chain.
                Lane.objects.select_for_update().filter(pk=lane.pk).first()

                band = Band.objects.create(
                    lane=lane,
                    detection_source="MANUAL",
                    band_type=band_type,
                    position_y=data.get("position_y"),
                    polygon=polygon if polygon else None,
                    bbox_x=data.get("bbox_x", bbox_x),
                    bbox_y=data.get("bbox_y", bbox_y),
                    bbox_width=data.get("bbox_width", bbox_width),
                    bbox_height=data.get("bbox_height", bbox_height),
                    estimated_mw_kda=data.get("estimated_mw_kda"),
                    label=data.get("label", ""),
                    notes=data.get("notes", ""),
                )

                # Update analysis counts
                analysis.update_counts()
            break
        except OperationalError as exc:
            # Deadlock detected — Postgres already rolled back our work.
            # Retry once; if it persists, surface a 409 so the client
            # knows to wait and try again rather than seeing a generic 500.
            if attempt == 1 and "deadlock" in str(exc).lower():
                logger.warning(
                    f"Deadlock on api_lane_bands lane={lane.pk}, retrying once",
                )
                continue
            logger.exception(f"Concurrent conflict creating band: {exc}")
            return json_error(
                "Another change to this lane was in progress. Please retry.",
                409,
            )
        except Exception as e:
            logger.exception(f"Error creating band: {e}")
            return json_error("An unexpected error occurred. Please try again.")

    logger.info(
        f"Created band in lane {lane.lane_number}",
        user=request.user.username,
        analysis_id=str(analysis.pk),
        band_id=str(band.pk),
    )

    return JsonResponse(
        {
            "success": True,
            "band": band_to_dict(band),
        },
        status=201,
    )


@login_required
@require_http_methods(["POST"])
def api_lane_apply_ladder_template(request, pk):
    """
    POST: Apply a ladder template to auto-fill MW values for bands in a lane.

    This is a quick way to assign molecular weights to bands in a LADDER lane
    by selecting a template and having the MW values auto-populated based on
    band position (top to bottom = high MW to low MW).

    Body:
    - template_id: UUID of the ladder template to apply

    Returns:
    - success: boolean
    - bands_updated: Number of bands with MW assigned
    - warnings: Array of warning messages (e.g., band count mismatch)
    - bands: Updated band data
    """
    from gel_analyzer.models import LadderTemplate

    lane = get_object_or_404(Lane.objects.select_related("analysis").prefetch_related("bands"), pk=pk)
    analysis = lane.analysis

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    # Verify lane is LADDER type
    if lane.lane_type != Lane.LaneType.LADDER:
        return json_error("This operation is only available for LADDER type lanes", 400)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    template_id = data.get("template_id")
    if not template_id:
        return json_error("template_id is required")

    # Get template with bands
    template = get_object_or_404(LadderTemplate.objects.prefetch_related("bands"), pk=template_id)

    try:
        # Get bands sorted by position_y (top to bottom = high MW to low MW)
        bands = list(lane.bands.order_by("position_y"))

        # Get template MW values sorted by band_order (1 = highest MW)
        template_bands = list(template.bands.order_by("band_order"))
        template_mws = [tb.mw_kda for tb in template_bands]

        warnings = []
        bands_updated = 0

        # Check for mismatch
        if len(bands) > len(template_mws):
            extra_count = len(bands) - len(template_mws)
            warnings.append(f"{extra_count} extra band(s) detected - template only has {len(template_mws)} bands")
        elif len(bands) < len(template_mws):
            missing_count = len(template_mws) - len(bands)
            warnings.append(f"{missing_count} template band(s) not assigned - only {len(bands)} bands detected")

        # Assign MW values to bands
        with transaction.atomic():
            for i, band in enumerate(bands):
                if i < len(template_mws):
                    band.estimated_mw_kda = template_mws[i]
                    band.mw_estimation_method = f"TEMPLATE:{template.code}"
                    band.save(update_fields=["estimated_mw_kda", "mw_estimation_method"])
                    bands_updated += 1
                else:
                    # Extra bands without MW - clear any existing value
                    if band.estimated_mw_kda is not None:
                        band.estimated_mw_kda = None
                        band.mw_estimation_method = ""
                        band.save(update_fields=["estimated_mw_kda", "mw_estimation_method"])

            # Update lane's ladder_template reference
            lane.ladder_template = template
            lane.save(update_fields=["ladder_template"])

        logger.info(
            f"Applied ladder template {template.name} to lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            template_id=str(template.pk),
            bands_updated=bands_updated,
            warnings=warnings,
        )

        # Fetch updated bands
        updated_bands = lane.bands.order_by("position_y")

        return JsonResponse(
            {
                "success": True,
                "bands_updated": bands_updated,
                "template_name": template.name,
                "template_band_count": len(template_mws),
                "lane_band_count": len(bands),
                "warnings": warnings if warnings else None,
                "bands": [band_to_dict(b) for b in updated_bands],
            }
        )

    except Exception as e:
        logger.exception(f"Error applying ladder template to lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_band_detail(request, pk):
    """
    GET: Get band details.
    PUT: Update band properties. A band_type write keeps the v1 PATCH's rule (check_band_type / apply_band_type):
         CALIBRATION without a stored calibration point is refused (400; the editor sends the type with its amount
         through the v1 PATCH), any other type deletes the band's point.
    DELETE: Delete band.
    """
    band = get_object_or_404(Band.objects.select_related("lane__analysis"), pk=pk)
    analysis = band.lane.analysis

    if request.method == "GET":
        return JsonResponse({"band": band_to_dict(band)})

    elif request.method == "PUT":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        data = parse_json_body(request)
        if data is None:
            return json_error("Invalid JSON in request body")

        # Update allowed fields
        updatable_fields = [
            "position_y",
            "polygon",
            "bbox_x",
            "bbox_y",
            "bbox_width",
            "bbox_height",
            "estimated_mw_kda",
            "label",
            "notes",
            "band_type",
        ]
        # Before the type is set: the stored band decides whether it holds a calibration point.
        if "band_type" in data:
            try:
                check_band_type(band, data["band_type"])
            except BandTypeRefused as refusal:
                return json_error(str(refusal))
        for field in updatable_fields:
            if field in data:
                setattr(band, field, data[field])

        # Recalculate bbox if polygon changed
        if "polygon" in data and data["polygon"] and len(data["polygon"]) >= 3:
            polygon = data["polygon"]
            xs = [p[0] for p in polygon]
            ys = [p[1] for p in polygon]
            band.bbox_x = min(xs)
            band.bbox_y = min(ys)
            band.bbox_width = max(xs) - band.bbox_x
            band.bbox_height = max(ys) - band.bbox_y

        with transaction.atomic():
            band.save()
            if "band_type" in data:
                apply_band_type(band)

        logger.info(f"Updated band {band.pk}", user=request.user.username, band_id=str(band.pk))

        return JsonResponse(
            {
                "success": True,
                "band": band_to_dict(band),
            }
        )

    elif request.method == "DELETE":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        try:
            band_id = str(band.pk)
            band.delete()

            # Update analysis counts
            analysis.update_counts()

            logger.info(f"Deleted band {band_id}", user=request.user.username, analysis_id=str(analysis.pk))

            return JsonResponse({"success": True})

        except Exception as e:
            logger.exception(f"Error deleting band: {e}")
            return json_error("An unexpected error occurred. Please try again.", 500)


@login_required
@require_http_methods(["POST"])
def api_band_split(request, pk):
    """
    POST: Split a band into two halves atomically.

    Replaces the legacy frontend pattern of issuing DELETE → CREATE upper →
    CREATE lower as three sequential roundtrips (which forced the client to
    follow with a /data/ reload to pick up the new IDs — four roundtrips
    total). One transactional endpoint here cuts the perceived latency for
    the split UX from ~600-1200ms to a single roundtrip, AND removes the
    "DELETE arrives after the CREATEs → 3 bands left in DB" failure mode
    that motivated the original sequencing comment in _splitBand.

    The polygon math (intersection at splitY, sorting the upper/lower
    polygons) stays on the client — it's a pure CPU operation with no DB
    involvement, and replicating it server-side would just duplicate code
    that already works in gel-viewer.js::_splitBand.

    Body:
        upper: {polygon, position_y, bbox_x, bbox_y, bbox_width, bbox_height,
                band_type, label, notes}
        lower: {same shape as upper}

    Returns:
        {success: True, upper: <band dict>, lower: <band dict>,
         deleted_id: "<uuid>"}
    """
    band = get_object_or_404(Band.objects.select_related("lane__analysis"), pk=pk)
    analysis = band.lane.analysis
    lane = band.lane

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    upper = data.get("upper")
    lower = data.get("lower")
    if not upper or not lower:
        return json_error('Both "upper" and "lower" payloads are required')

    def _band_payload(d):
        # Mirror the bbox-from-polygon fallback used in api_lane_bands so
        # clients can omit bbox_* when they pass polygon — keeps the wire
        # format flexible.
        polygon = d.get("polygon") or []
        bbox_x = d.get("bbox_x")
        bbox_y = d.get("bbox_y")
        bbox_width = d.get("bbox_width")
        bbox_height = d.get("bbox_height")
        if polygon and len(polygon) >= 3 and bbox_x is None:
            xs = [p[0] for p in polygon]
            ys = [p[1] for p in polygon]
            bbox_x = min(xs)
            bbox_y = min(ys)
            bbox_width = max(xs) - bbox_x
            bbox_height = max(ys) - bbox_y
        return {
            "detection_source": "MANUAL",
            "band_type": d.get("band_type", band.band_type or "OTHER"),
            "position_y": d.get("position_y"),
            "polygon": polygon or None,
            "bbox_x": bbox_x,
            "bbox_y": bbox_y,
            "bbox_width": bbox_width,
            "bbox_height": bbox_height,
            "estimated_mw_kda": d.get("estimated_mw_kda"),
            "label": d.get("label", ""),
            "notes": d.get("notes", ""),
        }

    upper_payload, lower_payload = _band_payload(upper), _band_payload(lower)
    # Each half is a new band, without the split band's calibration point: a half typed CALIBRATION is refused, as
    # the v1 PATCH refuses CALIBRATION without a point. The editor sends OTHER for both after asking.
    for payload in (upper_payload, lower_payload):
        try:
            check_band_type(None, payload["band_type"])
        except BandTypeRefused as refusal:
            return json_error(f"A split half has no calibration point: {refusal}")

    try:
        with transaction.atomic():
            deleted_id = str(band.pk)
            # If the original was a CALIBRATION band, its
            # ProteinQuantCalibrationPoint cascade-deletes with the band
            # (OneToOne CASCADE). The halves cannot inherit the load amount
            # automatically — splitting changes what's quantified, so the
            # user needs to re-mark whichever half is the calibration
            # standard. Logged so support can correlate "missing calibration
            # point after split" reports without scraping the audit log.
            if band.band_type == "CALIBRATION":
                logger.info(
                    f"Split discarded CALIBRATION quant_point for band {deleted_id}",
                    band_id=deleted_id,
                    analysis_id=str(analysis.pk),
                )
            band.delete()
            upper_band = Band.objects.create(lane=lane, **upper_payload)
            lower_band = Band.objects.create(lane=lane, **lower_payload)
            # Inside the same transaction so a failed count update rolls
            # back the delete + creates together; the alternative left
            # total_bands stale until the next save when update_counts()
            # raised post-commit.
            analysis.update_counts()

        logger.info(
            f"Split band {deleted_id} into {upper_band.pk} / {lower_band.pk}",
            user=request.user.username,
            analysis_id=str(analysis.pk),
            lane_id=str(lane.pk),
        )

        return JsonResponse(
            {
                "success": True,
                "deleted_id": deleted_id,
                "upper": band_to_dict(upper_band),
                "lower": band_to_dict(lower_band),
            }
        )
    except Exception as e:
        logger.exception(f"Error splitting band {pk}: {e}")
        # transaction.atomic rolled back already; the original band is intact.
        return json_error("An unexpected error occurred while splitting. Please try again.", 500)


@login_required
@require_http_methods(["GET"])
def api_analysis_data(request, pk):
    """
    GET: Get full analysis data with all lanes and bands.

    Used to load the initial state of the annotation viewer. ``analysis.readout_reference_lane_id``
    and ``gel_image.assay`` (``{"id", "name", "readout"}`` or null) drive the lane menu's "Use as
    HCP reference" entry and the REF badge; ``analysis.can_write`` disables that entry for a reader.

    ``page_summary`` is the analysis page's composition (``analysis_detail.summary_payload``: the readout,
    its checks, the lane cells) and each band carries its ``role`` in the gel's readout
    (``analysis_detail.band_role_map``: ``aggregate`` / ``main`` / ``clipping``, ``hcp`` / ``left_out``, else
    null -- roles exist where a densitometry run left values, and a band edit wipes them). Both are computed
    in a guard, as on the densitometry API: a failure logs and serves ``null`` / no role, never a 500 on the
    editor's only load.
    """
    from gel_analyzer.services.analysis_detail import (
        band_role_map,
        page_summary,
        summary_lanes_prefetch,
        summary_payload,
    )
    from gel_analyzer.services.readout_publisher import assay_summary

    # The lanes whole (summary, sample, bands with their densitometry): what page_summary and lane_readouts
    # read with no query of their own, and lane_to_dict's sample with no per-lane query.
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related("gel_image__assay").prefetch_related(summary_lanes_prefetch()), pk=pk
    )
    lanes = list(analysis.lanes.all())

    summary_json, roles = None, {}
    try:
        gel_summary = page_summary(analysis, lanes)
        summary_json = summary_payload(analysis, gel_summary, lanes)
        roles = band_role_map(gel_summary, lanes)
    except Exception:
        logger.exception(f"page_summary failed for analysis {analysis.id} (annotation data)")

    lanes_data = [lane_to_dict(lane) for lane in lanes]
    for lane_data in lanes_data:
        for band_data in lane_data["bands"]:
            band_data["role"] = roles.get(band_data["id"])

    return JsonResponse(
        {
            "analysis": {
                "id": str(analysis.pk),
                "name": analysis.name,
                "status": analysis.status,
                "is_editable": analysis.is_editable,
                "can_write": user_can_write_gel_analyzer(request.user),
                "readout_reference_lane_id": analysis.readout_reference_lane_id,
                "total_lanes": analysis.total_lanes,
                "total_bands": analysis.total_bands,
            },
            "gel_image": {
                "id": str(analysis.gel_image.pk),
                "url": analysis.gel_image.display_file.url if analysis.gel_image.display_file else None,
                "width": analysis.gel_image.width,
                "height": analysis.gel_image.height,
                "gel_type": analysis.gel_image.gel_type,
                "assay": assay_summary(analysis),
            },
            "lanes": lanes_data,
            "page_summary": summary_json,
        }
    )


def _proxied_file(gel_image):
    """The file ``api_image_proxy`` serves: the display file, else the original upload (falsy when neither is set)."""
    return gel_image.display_file or gel_image.original_file


def image_proxy_etag(request, pk):
    """The image proxy's validator (sample comparison spec 2026-10-11 §3.7): a digest of the served file's storage
    name and its ``storage.size()``. One rule on FileSystemStorage (tests) and Azure (one blob-properties call, no
    download). A crop or a new display file is saved under a new name (the storage never overwrites), so a changed
    file changes the validator.

    Hashed, not sent raw: Django MIME-encodes a header value outside latin-1, which then never matches again, and a
    ``"`` or a ``,`` breaks ``parse_etags``; a storage name built from an uploaded filename promises none of that.

    No ``last_modified_func`` beside it: on Azure ``get_modified_time()`` is a second blob-properties round trip
    (``size()`` makes its own), and ``If-None-Match`` already decides before ``If-Modified-Since`` (RFC 9110 §13.2.2).

    Never raises on a missing file or a storage error: it returns None (no validator), and the view answers exactly
    as it did without one (the file, or its 404)."""
    gel_image = GelImage.objects.filter(pk=pk).only("display_file", "original_file").first()
    if gel_image is None:
        return None
    image_file = _proxied_file(gel_image)
    if not image_file:
        return None
    try:
        size = image_file.storage.size(image_file.name)
    except Exception as exc:  # FileNotFoundError on disk; ResourceNotFoundError / AzureError on Azure
        logger.warning("Image proxy {}: no ETag, the storage could not size {}: {}", pk, image_file.name, exc)
        return None
    digest = hashlib.sha256(f"{image_file.name}\n{size}".encode()).hexdigest()
    return f'"{digest[:32]}"'


@login_required
@require_http_methods(["GET"])
@cache_control(private=True, no_cache=True)
@condition(etag_func=image_proxy_etag)
def api_image_proxy(request, pk):
    """
    Proxy endpoint for gel image files.

    Serves the image through Django to avoid CORS issues when images
    are stored on external storage (e.g., Azure Blob Storage).

    This is used by the auto-detect and auto-enhance features which need to read
    pixel data from the canvas, which would otherwise fail due to
    CORS tainted canvas restrictions.

    Validators (sample comparison spec 2026-10-11 §3.7): ``condition`` sends ``image_proxy_etag`` as the ``ETag``
    and answers a matching ``If-None-Match`` with 304 before this body runs, so a page showing the same gel again
    downloads nothing. ``cache_control`` puts ``private, no-cache`` on the 200 and the 304 alike: the browser
    revalidates on every view and never shows a replaced (cropped) image. Both sit inside ``login_required``, so an
    anonymous request is redirected to the login page and never gets a 304.
    """
    gel_image = get_object_or_404(GelImage, pk=pk)

    # Prefer display_file, fallback to original_file
    image_file = _proxied_file(gel_image)
    if not image_file:
        raise Http404("Image file not found")

    try:
        # Read file content
        file_content = image_file.read()

        # Determine content type based on file extension
        filename = image_file.name.lower()
        if filename.endswith(".png"):
            content_type = "image/png"
        elif filename.endswith((".jpg", ".jpeg")):
            content_type = "image/jpeg"
        elif filename.endswith(".gif"):
            content_type = "image/gif"
        elif filename.endswith((".tif", ".tiff")):
            content_type = "image/tiff"
        else:
            content_type = "application/octet-stream"

        response = HttpResponse(file_content, content_type=content_type)
        response["Content-Length"] = len(file_content)

        return response

    except Exception as e:
        logger.exception(f"Error proxying image {pk}: {e}")
        raise Http404("Error reading image file") from e


@login_required
@require_http_methods(["POST"])
def api_analysis_yolo_results(request, pk):
    """
    POST: Save raw YOLO detection results to analysis.

    This stores the full detection output for reference,
    before user filtering/acceptance.

    Body:
    - detections: Array of detection objects from YOLO
    - inferred_gel_type: Inferred gel type (SDS_PAGE, DOT_BLOT, UNKNOWN)
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    # Save YOLO results
    analysis.yolo_detection_results = data.get("detections", [])
    analysis.yolo_gel_type_inference = data.get("inferred_gel_type", "")
    analysis.save(update_fields=["yolo_detection_results", "yolo_gel_type_inference"])

    logger.info(
        "Saved YOLO results for analysis",
        user=request.user.username,
        analysis_id=str(analysis.pk),
        detection_count=len(data.get("detections", [])),
        inferred_gel_type=data.get("inferred_gel_type", ""),
    )

    return JsonResponse(
        {
            "success": True,
            "detection_count": len(data.get("detections", [])),
            "inferred_gel_type": data.get("inferred_gel_type", ""),
        }
    )


@login_required
@require_http_methods(["POST"])
def api_bulk_lanes(request, pk):
    """
    POST: Create multiple lanes in a single transaction.

    Used by YOLO auto-detect to create all accepted lanes at once,
    instead of making N separate API calls.

    Body:
    - lanes: Array of lane objects to create

    Returns:
    - success: boolean
    - lanes: Array of created lane objects with server-assigned IDs
    - count: Number of lanes created
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    lanes_data = data.get("lanes", [])
    if not lanes_data:
        return json_error("No lanes provided", 400)
    # Rule 1 on every lane before anything is written: one refused lane refuses the request.
    size = image_size_of(analysis)
    try:
        lanes_data = [with_lane_geometry(lane_data, None, size) for lane_data in lanes_data]
    except GeometryRefused as exc:
        return json_error(f"Invalid lane geometry: {exc}")

    created_lanes = []

    try:
        with transaction.atomic():
            # Calculate starting lane number
            max_lane = analysis.lanes.aggregate(Max("lane_number"))["lane_number__max"] or 0
            next_lane_number = max_lane + 1

            for lane_data in lanes_data:
                lane = Lane.objects.create(
                    analysis=analysis,
                    lane_number=next_lane_number,  # Temporary, will be fixed by renumber_lanes
                    lane_type=lane_data.get("lane_type", "SAMPLE"),
                    detection_source=lane_data.get("detection_source", "MANUAL"),
                    confidence=lane_data.get("confidence"),
                    # Shape and geometry
                    lane_shape=lane_data.get("lane_shape", "RECTANGLE"),
                    x=lane_data.get("x", 0),
                    y=lane_data.get("y", 0),
                    width=lane_data.get("width", 50),
                    height=lane_data.get("height", 100),
                    polygon=lane_data.get("polygon"),
                    # Sample conditions and load
                    is_reduced=lane_data.get("is_reduced"),
                    protein_load_ug=lane_data.get("protein_load_ug"),
                    protein_load_type=lane_data.get("protein_load_type", ""),
                    # Sample info
                    sample_name=lane_data.get("sample_name", ""),
                    notes=lane_data.get("notes", ""),
                )
                created_lanes.append(lane)
                next_lane_number += 1

            # Renumber lanes once (based on X position, left to right)
            analysis.renumber_lanes()
            analysis.update_counts()

            # Refresh all lanes to get updated lane numbers
            for lane in created_lanes:
                lane.refresh_from_db()

        logger.info(
            f"Bulk created {len(created_lanes)} lanes",
            user=request.user.username,
            analysis_id=str(analysis.pk),
            lane_count=len(created_lanes),
        )

        return JsonResponse(
            {
                "success": True,
                "lanes": [lane_to_dict(lane) for lane in created_lanes],
                "count": len(created_lanes),
            },
            status=201,
        )

    except Exception as e:
        logger.exception(f"Error bulk creating lanes: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["PUT"])
def api_bulk_update_lanes(request, pk):
    """
    PUT: Update multiple lanes in a single transaction.

    Body:
    - lanes: Array of {id, ...fields to update}

    A lane_type leaving CALIBRATION/CONTROL while the lane's bands hold calibration points refuses the whole request
    with the v1 PATCH's 409 unless ?force=true (guard_lane_type_change).

    Returns:
    - success: boolean
    - lanes: Array of updated lane objects
    - count: Number of lanes updated
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    lanes_data = data.get("lanes", [])
    if not lanes_data:
        return json_error("No lanes provided", 400)
    # Before the atomic block: a refusal returned from inside it would commit the lanes already written.
    for lane_data in lanes_data:
        refusal = loading_volume_refusal(lane_data) if isinstance(lane_data, dict) else None
        if refusal:
            return json_error(f"Lane id {lane_data.get('id')}: {refusal}")

    updated_lanes = []
    x_changed = False

    updatable_fields = [
        "lane_type",
        "lane_shape",
        "x",
        "y",
        "width",
        "height",
        "polygon",
        "is_reduced",
        "protein_load_ug",
        "loading_volume_ul",
        "protein_load_type",
        "sample_name",
        "notes",
    ]

    size = image_size_of(analysis)
    force = wants_force(request)
    try:
        with transaction.atomic():
            for lane_data in lanes_data:
                lane_id = lane_data.get("id")
                if not lane_id:
                    continue

                # Only update lanes belonging to this analysis
                lane = Lane.objects.filter(pk=lane_id, analysis=analysis).first()
                if not lane:
                    continue

                # Rule 1, the calibration points' guard, then the ladder template; a refusal raises out of the atomic
                # block: nothing of this request is written, no point purged.
                lane_data = with_lane_geometry(lane_data, lane, size)
                if "lane_type" in lane_data:
                    guard_lane_type_change(lane, lane_data["lane_type"], force=force)
                lane_data = with_ladder_template(lane_data, lane)
                old_x = lane.x

                # Update allowed fields
                for field in updatable_fields:
                    if field in lane_data:
                        setattr(lane, field, lane_data[field])

                # The ladder template follows the lane type (with_ladder_template)
                if "ladder_template_id" in lane_data:
                    lane.ladder_template_id = lane_data["ladder_template_id"]

                lane.save()
                updated_lanes.append(lane)

                # Track if any X position changed
                if lane.x != old_x:
                    x_changed = True

            # Renumber lanes if any position changed
            if x_changed:
                analysis.renumber_lanes()
                for lane in updated_lanes:
                    lane.refresh_from_db()

        logger.info(
            f"Bulk updated {len(updated_lanes)} lanes",
            user=request.user.username,
            analysis_id=str(analysis.pk),
            lane_count=len(updated_lanes),
        )

        return JsonResponse(
            {
                "success": True,
                "lanes": [lane_to_dict(lane) for lane in updated_lanes],
                "count": len(updated_lanes),
            }
        )

    except GeometryRefused as exc:
        return json_error(f"Invalid lane geometry: {exc}")
    except LadderTemplateRefused as exc:  # raised in the loop: `lane` is the lane refused
        return json_error(f"Lane {lane.lane_number}: {exc}")
    except CalibrationPointsHeld as refusal:
        return calibration_points_refusal(refusal)
    except Exception as e:
        logger.exception(f"Error bulk updating lanes: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_bulk_delete_lanes(request, pk):
    """
    POST: Delete multiple lanes in a single transaction.

    Using POST because DELETE with body is not universally supported.

    Body:
    - lane_ids: Array of lane IDs to delete

    Returns:
    - success: boolean
    - deleted_count: Number of lanes deleted
    - lanes: Updated list of remaining lanes
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    lane_ids = data.get("lane_ids", [])
    if not lane_ids:
        return json_error("No lane IDs provided", 400)

    try:
        with transaction.atomic():
            # Only delete lanes belonging to this analysis
            deleted_count = Lane.objects.filter(pk__in=lane_ids, analysis=analysis).delete()[0]

            # Renumber remaining lanes and update counts
            analysis.renumber_lanes()
            analysis.update_counts()

        logger.info(
            f"Bulk deleted {deleted_count} lanes",
            user=request.user.username,
            analysis_id=str(analysis.pk),
            deleted_count=deleted_count,
        )

        # Return updated lanes for client refresh
        updated_lanes = [
            lane_to_dict(lane) for lane in analysis.lanes.prefetch_related("bands").order_by("lane_number")
        ]

        return JsonResponse(
            {
                "success": True,
                "deleted_count": deleted_count,
                "lanes": updated_lanes,
            }
        )

    except Exception as e:
        logger.exception(f"Error bulk deleting lanes: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_bulk_delete_bands(request, pk):
    """
    POST: Delete multiple bands in a single transaction.

    Using POST because DELETE with body is not universally supported.

    Body:
    - band_ids: Array of band IDs to delete (optional - if not provided, deletes ALL bands)

    Returns:
    - success: boolean
    - deleted_count: Number of bands deleted
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    try:
        with transaction.atomic():
            # If band_ids provided, delete specific bands; otherwise delete all
            if data and data.get("band_ids"):
                band_ids = data.get("band_ids", [])
                deleted_count = Band.objects.filter(pk__in=band_ids, lane__analysis=analysis).delete()[0]
            else:
                # Delete ALL bands for this analysis
                deleted_count = Band.objects.filter(lane__analysis=analysis).delete()[0]

            # Update counts
            analysis.update_counts()

        logger.info(
            f"Bulk deleted {deleted_count} bands",
            user=request.user.username,
            analysis_id=str(analysis.pk),
            deleted_count=deleted_count,
        )

        return JsonResponse(
            {
                "success": True,
                "deleted_count": deleted_count,
            }
        )

    except Exception as e:
        logger.exception(f"Error bulk deleting bands: {e}")
        return json_error("An unexpected error occurred. Please try again.")


# ============================================================================
# Band Detection API Endpoints (Auto d1/d2 Derivative)
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_detect_bands_lane(request, pk):
    """
    POST: Detect bands in a single lane (preview mode).

    Returns detected bands without saving to database.
    Use this for previewing detection with different parameters.

    Body:
    - params: Optional detection parameters dict
      - sensitivity: 0-1 (default 0.5)
      - min_band_width_px: int (default 5)
      - max_band_width_px: int (default 100)
      - smoothing_window: int (default 11)
      - peak_prominence: 0-1 (default 0.1)
      - background_method: str (default 'rolling_ball')
      - profile_width_percent: 10-100 (default 50)

    Returns:
    - success: boolean
    - bands: Array of detected band objects (not saved)
    - band_count: Number of bands detected
    - profile: Optional intensity profile data for visualization
    """
    from gel_analyzer.services.band_detection import BandDetectionParams, BandDetectionService
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}

    try:
        try:
            params = BandDetectionParams.from_dict(params_dict)
        except ValueError as e:  # the params' own range checks (models.py) or an unknown background_method
            logger.warning(f"Invalid detection params: {e}")
            return json_error(f"Invalid parameters: {e}")

        # Load image
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)

        # Run detection (preview mode - no save)
        service = BandDetectionService(params)
        result = service.detect_bands_in_lane(lane, image)

        # Build response with profile data for visualization
        response = result.to_dict()

        # Include profile data for plotting in frontend
        if result.profile and result.success:
            profile_data = {
                "y_positions": result.profile.y_positions,
                "raw_intensities": result.profile.raw_intensities,
                "processed_intensities": result.profile.processed_intensities,
                "background": result.profile.background,
                "was_inverted": result.profile.was_inverted,
                "valleys": result.profile.valley_indices,
                "threshold_used": result.threshold_used,
            }
            # Include derivative data when computed
            if result.profile.first_derivative:
                profile_data["first_derivative"] = [round(v, 4) for v in result.profile.first_derivative]
                profile_data["second_derivative"] = [round(v, 4) for v in result.profile.second_derivative]
                profile_data["derivative_zero_crossings"] = result.profile.derivative_zero_crossings
            response["profile"] = profile_data

        logger.info(
            f"Band detection preview for lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            band_count=len(result.bands),
            params=params_dict,
        )

        return JsonResponse(response)

    except Exception as e:  # a ValueError from the detection itself carries numpy's text, not the params'
        error = public_error_text(
            logger, e, public="The band detection failed.", log=f"Band detection failed for lane {pk}", request=request
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_diagnostic(request, pk):
    """
    POST: Run detection with multiple parameter combinations for diagnostics.

    Sweeps key parameters and reports band count + rejection stats for each
    combination. Helps diagnose why detection returns 0 bands.

    Body (optional):
    - base_params: dict of base detection parameters

    Returns:
    - success: boolean
    - sweep_results: list of {params, band_count, diagnostics}
    - summary: overview of what kills peaks
    """
    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    data = parse_json_body(request)
    base_dict = data.get("params", data) if data else {}

    try:
        from gel_analyzer.services.band_detection import BandDetectionParams, BandDetectionService
        from gel_analyzer.services.file_handler import GelFileHandler

        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)

        # Define sweep grid — test most impactful parameters
        sweep_configs = [
            {"label": "User params (as-is)", "overrides": {}},
            {
                "label": "Min thresholds",
                "overrides": {
                    "d2_significance_factor": 1.0,
                    "slope_threshold_factor": 0.5,
                    "threshold_factor": 1.0,
                    "min_snr": 0.5,
                },
            },
            {"label": "Low d2 only", "overrides": {"d2_significance_factor": 1.0}},
            {"label": "Low slope only", "overrides": {"slope_threshold_factor": 0.5}},
            {"label": "Low threshold_factor only", "overrides": {"threshold_factor": 1.0}},
            {"label": "Low SNR only", "overrides": {"min_snr": 0.5}},
            {"label": "Wide bands allowed", "overrides": {"max_band_width_px": 200, "min_band_width_px": 2}},
            {"label": "Small derivative window", "overrides": {"derivative_window": 7}},
            {"label": "Large derivative window", "overrides": {"derivative_window": 25}},
            {
                "label": "All relaxed + wide",
                "overrides": {
                    "d2_significance_factor": 1.0,
                    "slope_threshold_factor": 0.5,
                    "threshold_factor": 1.0,
                    "min_snr": 0.5,
                    "max_band_width_px": 200,
                    "min_band_width_px": 2,
                },
            },
        ]

        results = []
        for config in sweep_configs:
            params_dict = {**base_dict, **config["overrides"]}
            params = BandDetectionParams.from_dict(params_dict)
            service = BandDetectionService(params)
            result = service.detect_bands_in_lane(lane, image)
            diag = result.detection_diagnostics or {}
            results.append(
                {
                    "label": config["label"],
                    "overrides": config["overrides"],
                    "band_count": len(result.bands),
                    "diagnostics": diag,
                }
            )

        # Build summary: what's the main bottleneck?
        user_result = results[0]
        min_result = results[1]
        summary_lines = []
        if user_result["band_count"] == 0 and min_result["band_count"] > 0:
            summary_lines.append(
                f"With ALL thresholds at minimum: {min_result['band_count']} bands found. User params are too strict."
            )
        elif min_result["band_count"] == 0:
            summary_lines.append(
                "Even with ALL thresholds at minimum: 0 bands. "
                "Issue is NOT thresholds — may be profile processing, "
                "background subtraction, or derivative computation."
            )

        # Check which individual params matter
        for r in results[2:]:
            if r["band_count"] > user_result["band_count"]:
                summary_lines.append(
                    f"'{r['label']}' → {r['band_count']} bands (vs {user_result['band_count']} with user params)"
                )

        return JsonResponse(
            {
                "success": True,
                "sweep_results": results,
                "summary": summary_lines,
            }
        )

    except Exception as e:
        error = public_error_text(
            logger,
            e,
            public="The detection diagnostic failed.",
            log=f"Detection diagnostic failed for lane {pk}",
            request=request,
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_lane_save(request, pk):
    """
    POST: Detect bands in a single lane and save to database.

    Creates Band model instances for detected bands.
    Optionally deletes existing auto-detected bands first.

    Body:
    - params: Optional detection parameters dict (see api_detect_bands_lane)
    - delete_existing: bool (default True) - delete existing auto-detected bands first

    Returns:
    - success: boolean
    - bands: Array of saved band objects with IDs
    - band_count: Number of bands saved
    """
    from gel_analyzer.services.band_detection import BandDetectionParams, BandDetectionService
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)
    analysis = lane.analysis

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}
    delete_existing = data.get("delete_existing", True) if data else True

    try:
        try:
            params = BandDetectionParams.from_dict(params_dict)
        except ValueError as e:  # the params' own range checks (models.py) or an unknown background_method
            logger.warning(f"Invalid detection params: {e}")
            return json_error(f"Invalid parameters: {e}")

        # Load image
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Run detection and save
        service = BandDetectionService(params)
        result = service.detect_and_save(
            lane=lane,
            image=image,
            user=request.user,
            delete_existing=delete_existing,
        )

        # Update analysis counts
        analysis.update_counts()

        # Fetch saved bands with their IDs (AUTO + SAM are both auto-detected)
        saved_bands = lane.bands.filter(
            detection_source__in=[Band.DetectionSource.AUTO, Band.DetectionSource.SAM]
        ).order_by("position_y")

        logger.info(
            f"Saved {len(result.bands)} auto-detected bands for lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            band_count=len(result.bands),
        )

        response_data = {
            "success": result.success,
            "bands": [band_to_dict(b) for b in saved_bands],
            "band_count": len(result.bands),
            "created_count": len(result.bands),
            "processing_time_ms": result.processing_time_ms,
            "error_message": result.error_message,
        }
        # Include diagnostics for debugging param flow
        if result.detection_diagnostics:
            response_data["diagnostics"] = result.detection_diagnostics
        return JsonResponse(response_data)

    except Exception as e:  # a ValueError from the detection itself carries numpy's text, not the params'
        error = public_error_text(
            logger, e, public="The band detection failed.", log=f"Band detection failed for lane {pk}", request=request
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_bulk(request, pk):
    """
    POST: Detect bands in multiple lanes of an analysis.

    Can run in preview mode (returns results without saving)
    or save mode (creates Band instances).

    Body:
    - params: Optional detection parameters dict
    - lane_ids: Optional array of specific lane IDs to process (null = all lanes)
    - save_results: bool (default False) - save to database
    - delete_existing: bool (default True) - delete existing auto-detected bands first

    Returns:
    - success: boolean
    - lanes_processed: Number of lanes processed
    - total_bands: Total bands detected across all lanes
    - results: Array of per-lane results
    """
    from gel_analyzer.services.band_detection import BandDetectionParams, BandDetectionService
    from gel_analyzer.services.file_handler import GelFileHandler

    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}
    lane_ids = data.get("lane_ids") if data else None
    save_results = data.get("save_results", False) if data else False
    delete_existing = data.get("delete_existing", True) if data else True

    if save_results and not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    try:
        try:
            params = BandDetectionParams.from_dict(params_dict)
        except ValueError as e:  # the params' own range checks (models.py) or an unknown background_method
            logger.warning(f"Invalid detection params: {e}")
            return json_error(f"Invalid parameters: {e}")

        # Load image
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        # Get lanes to process
        lanes = analysis.lanes.all()
        if lane_ids:
            lanes = lanes.filter(pk__in=lane_ids)
        lanes = lanes.order_by("lane_number")

        if not lanes.exists():
            return JsonResponse(
                {
                    "success": True,
                    "lanes_processed": 0,
                    "total_bands": 0,
                    "results": [],
                }
            )

        # Run detection for each lane
        service = BandDetectionService(params)
        results = []

        with transaction.atomic():
            for lane in lanes:
                if save_results:
                    # Delete existing auto-detected bands if requested
                    if delete_existing:
                        Band.objects.filter(
                            lane=lane,
                            detection_source=Band.DetectionSource.AUTO,
                        ).delete()

                    result = service.detect_and_save(
                        lane=lane,
                        image=image,
                        user=request.user,
                        delete_existing=False,  # Already deleted above
                    )
                else:
                    result = service.detect_bands_in_lane(lane, image)

                results.append(result)

            # Update analysis counts if saved
            if save_results:
                analysis.update_counts()

        total_bands = sum(len(r.bands) for r in results)
        successful = sum(1 for r in results if r.success)

        logger.info(
            f"Bulk band detection for analysis {pk}",
            user=request.user.username,
            analysis_id=str(pk),
            lanes_processed=len(results),
            total_bands=total_bands,
            save_results=save_results,
        )

        return JsonResponse(
            {
                "success": True,
                "lanes_processed": len(results),
                "lanes_successful": successful,
                "total_bands": total_bands,
                "results": [r.to_dict() for r in results],
            }
        )

    except Exception as e:  # a ValueError from the detection itself carries numpy's text, not the params'
        error = public_error_text(
            logger,
            e,
            public="The band detection failed.",
            log=f"Bulk band detection failed for analysis {pk}",
            request=request,
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["GET"])
def api_detection_params_defaults(request):
    """
    GET: Get default band detection parameters.

    Returns the default parameter values for the detection panel UI.
    """
    from gel_analyzer.services.band_detection import BandDetectionParams

    defaults = BandDetectionParams()

    return JsonResponse(
        {
            "params": defaults.to_dict(),
            "ranges": {
                "sensitivity": {"min": 0, "max": 1, "step": 0.05},
                "min_band_width_px": {"min": 1, "max": 50, "step": 1},
                "max_band_width_px": {"min": 20, "max": 300, "step": 5},
                "smoothing_window": {"min": 3, "max": 51, "step": 2, "note": "Must be odd"},
                "peak_prominence": {"min": 0.01, "max": 0.5, "step": 0.01},
                "peak_distance": {"min": 1, "max": 50, "step": 1},
                "lane_edge_margin_percent": {"min": 0, "max": 40, "step": 1},
                "rolling_ball_radius": {"min": 10, "max": 200, "step": 5},
                "profile_width_percent": {"min": 10, "max": 100, "step": 5},
                "min_intensity_ratio": {"min": 1.0, "max": 5.0, "step": 0.1},
                "threshold_factor": {"min": 1.0, "max": 10.0, "step": 0.5},
                "min_valley_depth_factor": {"min": 0.5, "max": 5.0, "step": 0.5},
            },
            "background_methods": [
                {"value": "rolling_ball", "label": "Rolling Ball"},
                {"value": "morphological", "label": "Morphological Opening"},
                {"value": "top_hat", "label": "Top-Hat Transform"},
                {"value": "linear_baseline", "label": "Linear Baseline"},
                {"value": "none", "label": "None"},
            ],
        }
    )


# ============================================================================
# Profile Peak Detection API Endpoints
# ============================================================================


# ============================================================================
# Async Band Detection API Endpoints (Celery Tasks)
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_detect_bands_async(request, pk):
    """
    POST: Start async band detection for an analysis.

    Triggers a Celery task for background processing.
    Use this for large analyses or when immediate response is needed.

    Body:
    - params: Optional detection parameters dict
    - lane_ids: Optional array of specific lane IDs (null = all lanes)
    - save_results: bool (default False)

    Returns:
    - success: boolean
    - task_id: Celery task ID for status polling
    """
    from gel_analyzer.tasks import detect_bands_bulk_task

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}
    raw_lane_ids = data.get("lane_ids") if data else None
    save_results = data.get("save_results", False) if data else False

    # Filter out temporary frontend IDs (e.g. 'temp_1_...')
    lane_ids = None
    if raw_lane_ids:
        lane_ids = []
        for lid in raw_lane_ids:
            with contextlib.suppress(ValueError, TypeError):
                lane_ids.append(int(lid))
        if not lane_ids:
            return json_error("No valid lane IDs provided. Save annotations first.", 400)

    if save_results and not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    # Start Celery task
    try:
        task = detect_bands_bulk_task.delay(
            analysis_id=str(pk),
            lane_ids=lane_ids,
            params_dict=params_dict,
            user_id=request.user.pk if save_results else None,
            save_results=save_results,
        )
    except Exception:
        logger.exception(f"Failed to start async band detection task for analysis {pk}")
        return json_error(
            "Could not start background task. The task queue may be unavailable. "
            "Please try the synchronous detection instead.",
            status=503,
        )

    logger.info(
        f"Started async band detection task {task.id}",
        user=request.user.username,
        analysis_id=str(pk),
        save_results=save_results,
    )

    return JsonResponse(
        {
            "success": True,
            "task_id": task.id,
            "analysis_id": str(pk),
            "message": "Band detection task started",
        }
    )


@login_required
@require_http_methods(["GET"])
def api_task_status(request, task_id):
    """
    GET: Get status of a Celery task.

    Returns task state and result if completed.
    Poll this endpoint to check async task progress.

    Returns:
    - task_id: str
    - state: PENDING | STARTED | SUCCESS | FAILURE | RETRY
    - result: Task result if completed (null otherwise)
    - error: Error message if failed
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "state": result.state,
        "result": None,
        "error": None,
    }

    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        logger.error(f"Celery task {task_id} failed: {result.result}")
        response["error"] = "An unexpected error occurred. Please try again."
    elif result.state == "PENDING":
        response["message"] = "Task is waiting to start"
    elif result.state == "STARTED":
        response["message"] = "Task is running"
    elif result.state == "PROGRESS":
        response["result"] = result.info  # Contains {current, total, lane_number}

    return JsonResponse(response)


# ============================================================================
# MW Ladder Template API Endpoints
# ============================================================================


def ladder_template_to_dict(template, include_bands=False):
    """Serialize LadderTemplate to dictionary."""
    data = {
        "id": str(template.pk),
        "name": template.name,
        "code": template.code,
        "manufacturer": template.manufacturer,
        "catalog_number": template.catalog_number,
        "category": template.category,
        "category_display": template.get_category_display(),
        "description": template.description,
        "band_count": template.band_count,
        "mw_range_min": template.mw_range_min,
        "mw_range_max": template.mw_range_max,
        "is_global": template.is_global,
        "is_active": template.is_active,
    }
    if include_bands:
        data["bands"] = [
            {
                "id": band.pk,
                "mw_kda": band.mw_kda,
                "band_order": band.band_order,
                "color": band.color,
                "color_display": band.get_color_display(),
                "is_reference_band": band.is_reference_band,
                "relative_intensity": band.relative_intensity,
            }
            for band in template.bands.order_by("band_order")
        ]
    return data


@login_required
@require_http_methods(["GET", "POST"])
def api_ladder_templates(request):
    """
    GET: List available ladder templates.

    Returns global templates and user's custom templates.
    Query params:
    - category: Filter by category (UNSTAINED, PRESTAINED, etc.)
    - manufacturer: Filter by manufacturer
    - active_only: If 'true', only show active templates (default true)

    POST: Create a new user template.
    """
    from gel_analyzer.models import LadderBandDefinition, LadderTemplate

    if request.method == "GET":
        from django.db.models import Q

        # Base queryset: global templates OR user's templates
        templates = LadderTemplate.objects.filter(Q(is_global=True) | Q(created_by=request.user)).select_related(
            "created_by"
        )

        # Apply filters
        category = request.GET.get("category")
        if category:
            templates = templates.filter(category=category)

        manufacturer = request.GET.get("manufacturer")
        if manufacturer:
            templates = templates.filter(manufacturer__icontains=manufacturer)

        active_only = request.GET.get("active_only", "true").lower() == "true"
        if active_only:
            templates = templates.filter(is_active=True)

        templates = templates.order_by("manufacturer", "name")

        return JsonResponse(
            {
                "templates": [ladder_template_to_dict(t) for t in templates],
                "count": templates.count(),
            }
        )

    elif request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return json_error("Invalid JSON in request body")

        # Validate required fields
        name = data.get("name", "").strip()
        if not name:
            return json_error("Template name is required")

        code = data.get("code", "").strip().upper()
        if not code:
            # Generate code from name
            import re

            code = re.sub(r"[^A-Z0-9]", "_", name.upper())[:50]

        # Check for duplicate code
        if LadderTemplate.objects.filter(code=code).exists():
            return json_error(f'Template code "{code}" already exists')

        try:
            with transaction.atomic():
                template = LadderTemplate.objects.create(
                    name=name,
                    code=code,
                    manufacturer=data.get("manufacturer", ""),
                    catalog_number=data.get("catalog_number", ""),
                    category=data.get("category", "UNSTAINED"),
                    description=data.get("description", ""),
                    is_global=False,  # User templates are never global
                    is_active=True,
                    created_by=request.user,
                )

                # Create bands if provided
                bands_data = data.get("bands", [])
                for band_data in bands_data:
                    LadderBandDefinition.objects.create(
                        template=template,
                        mw_kda=band_data.get("mw_kda"),
                        band_order=band_data.get("band_order"),
                        color=band_data.get("color", "NONE"),
                        is_reference_band=band_data.get("is_reference_band", False),
                        relative_intensity=band_data.get("relative_intensity"),
                    )

                # Update computed fields
                template.update_computed_fields()

            logger.info(
                f"Created ladder template {template.name}",
                user=request.user.username,
                template_id=str(template.pk),
            )

            return JsonResponse(
                {
                    "success": True,
                    "template": ladder_template_to_dict(template, include_bands=True),
                },
                status=201,
            )

        except Exception as e:
            logger.exception(f"Error creating ladder template: {e}")
            return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["GET"])
def api_default_ladder_template(request):
    """
    GET: Get the organization's default ladder template.

    Returns the template configured in settings.GEL_ANALYZER_DEFAULT_LADDER_TEMPLATE_CODE.
    """
    from django.conf import settings

    from gel_analyzer.models import LadderTemplate

    default_code = getattr(settings, "GEL_ANALYZER_DEFAULT_LADDER_TEMPLATE_CODE", "PRECISION_PLUS_ALL_BLUE")

    template = LadderTemplate.objects.filter(
        code=default_code,
        is_active=True,
    ).first()

    if template:
        return JsonResponse(
            {
                "template_id": str(template.pk),
                "template_name": template.name,
                "template_code": template.code,
                "manufacturer": template.manufacturer,
                "band_count": template.band_count,
            }
        )

    return JsonResponse({"template_id": None})


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_ladder_template_detail(request, pk):
    """
    GET: Get template details with bands.
    PUT: Update user template.
    DELETE: Delete user template (cannot delete global templates).
    """
    from django.db.models import Q

    from gel_analyzer.models import LadderBandDefinition, LadderTemplate

    # Only allow access to global templates or user's own templates
    template = get_object_or_404(LadderTemplate.objects.filter(Q(is_global=True) | Q(created_by=request.user)), pk=pk)

    if request.method == "GET":
        return JsonResponse(
            {
                "template": ladder_template_to_dict(template, include_bands=True),
            }
        )

    elif request.method == "PUT":
        # Can only edit user's own templates
        if template.is_global:
            return json_error("Cannot modify global templates", 403)

        if template.created_by != request.user:
            return json_error("Cannot modify other users' templates", 403)

        data = parse_json_body(request)
        if data is None:
            return json_error("Invalid JSON in request body")

        try:
            with transaction.atomic():
                # Update template fields
                updatable_fields = ["name", "manufacturer", "catalog_number", "category", "description", "is_active"]
                for field in updatable_fields:
                    if field in data:
                        setattr(template, field, data[field])
                template.save()

                # Update bands if provided
                if "bands" in data:
                    # Delete existing bands
                    template.bands.all().delete()

                    # Create new bands
                    for band_data in data["bands"]:
                        LadderBandDefinition.objects.create(
                            template=template,
                            mw_kda=band_data.get("mw_kda"),
                            band_order=band_data.get("band_order"),
                            color=band_data.get("color", "NONE"),
                            is_reference_band=band_data.get("is_reference_band", False),
                            relative_intensity=band_data.get("relative_intensity"),
                        )

                    # Update computed fields
                    template.update_computed_fields()

            logger.info(
                f"Updated ladder template {template.name}",
                user=request.user.username,
                template_id=str(template.pk),
            )

            return JsonResponse(
                {
                    "success": True,
                    "template": ladder_template_to_dict(template, include_bands=True),
                }
            )

        except Exception as e:
            logger.exception(f"Error updating ladder template: {e}")
            return json_error("An unexpected error occurred. Please try again.")

    elif request.method == "DELETE":
        # Can only delete user's own templates
        if template.is_global:
            return json_error("Cannot delete global templates", 403)

        if template.created_by != request.user:
            return json_error("Cannot delete other users' templates", 403)

        try:
            template_name = template.name
            template.delete()

            logger.info(
                f"Deleted ladder template {template_name}",
                user=request.user.username,
            )

            return JsonResponse({"success": True})

        except Exception as e:
            logger.exception(f"Error deleting ladder template: {e}")
            return json_error("An unexpected error occurred. Please try again.")


# ============================================================================
# MW Calibration API Endpoints
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_lane_match_template(request, pk):
    """
    POST: Match detected bands in lane to template bands.

    Preview mode - returns matches without saving calibration.
    Used for displaying calibration preview before committing.

    Body:
    - template_id: UUID of ladder template to match against

    Returns:
    - success: boolean
    - matches: Array of {band_id, template_band_order, mw_kda, position_y, rf}
    - suggested_method: Suggested calibration method based on band count
    """
    from gel_analyzer.models import LadderTemplate
    from gel_analyzer.services.calibration import CalibrationService

    lane = get_object_or_404(Lane.objects.select_related("analysis").prefetch_related("bands"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    template_id = data.get("template_id")
    if not template_id:
        return json_error("template_id is required")

    template = get_object_or_404(LadderTemplate, pk=template_id)

    try:
        service = CalibrationService()
        matches = service.match_bands_to_template(lane, template)

        # Suggest method based on band count
        if len(matches) >= 6:
            suggested_method = "LOG_LINEAR"  # Linear is robust with many points
        elif len(matches) >= 4:
            suggested_method = "LOG_LINEAR"  # Still prefer linear
        else:
            suggested_method = "LOG_LINEAR"  # Default to linear

        # Determine unmatched template bands
        matched_orders = {m.template_band_order for m in matches}
        template_bands = list(template.bands.order_by("band_order"))
        unmatched = [
            {"band_order": tb.band_order, "mw_kda": float(tb.mw_kda)}
            for tb in template_bands
            if tb.band_order not in matched_orders
        ]

        return JsonResponse(
            {
                "success": True,
                "matches": [m.to_dict() for m in matches],
                "matched_count": len(matches),
                "template_band_count": template.band_count,
                "unmatched_template_bands": unmatched,
                "suggested_method": suggested_method,
            }
        )

    except Exception as e:
        logger.exception(f"Error matching bands to template: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_analysis_calibrate(request, pk):
    """
    POST: Compute and save calibration for analysis.

    Body:
    - lane_id: ID of ladder lane to use for calibration
    - template_id: UUID of ladder template
    - method: Calibration method (LOG_LINEAR, POLYNOMIAL_2, POLYNOMIAL_3)
    - matches: Optional array of band matches (if pre-computed)

    Returns:
    - success: boolean
    - calibration: Saved calibration object
    - result: Calibration result with R², equation, coefficients
    """
    from gel_analyzer.models import LadderCalibration, LadderTemplate
    from gel_analyzer.services.calibration import CalibrationParams, CalibrationService

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    lane_id = data.get("lane_id")
    template_id = data.get("template_id")
    method = data.get("method", "LOG_LINEAR")
    excluded_band_ids = data.get("excluded_band_ids") or []
    if not isinstance(excluded_band_ids, list):
        return json_error("excluded_band_ids must be a list of band UUIDs")

    if not lane_id:
        return json_error("lane_id is required")

    # Get lane. Template is OPTIONAL — when the user has already assigned MW
    # values to ladder bands via the Band Editor, the fit consumes those
    # values directly and never touches the template. Requiring a template
    # purely for the "auto-attribute MW from a known brand" case made the
    # workflow needlessly heavy when MWs were already in the DB.
    lane = get_object_or_404(Lane.objects.filter(analysis=analysis), pk=lane_id)
    template = None
    if template_id:
        template = get_object_or_404(LadderTemplate, pk=template_id)

    try:
        # Configure calibration
        params = CalibrationParams(method=method)
        service = CalibrationService(params)

        # Pre-filter the matches so the user-excluded bands are dropped from the fit.
        matches, match_warnings = service.get_bands_with_assigned_mw(lane, excluded_band_ids=excluded_band_ids)

        # Compute calibration
        result = service.calibrate(lane, template, matches, match_warnings)

        if not result.success:
            return JsonResponse(
                {
                    "success": False,
                    "error_message": result.error_message,
                },
                status=400,
            )

        with transaction.atomic():
            # Delete existing calibration if any
            LadderCalibration.objects.filter(analysis=analysis).delete()

            # Create new calibration. excluded_band_ids is filtered to those
            # actually in this ladder lane so the saved record stays clean.
            lane_band_ids = {str(b_id) for b_id in lane.bands.values_list("id", flat=True)}
            excluded_for_lane = [b for b in excluded_band_ids if b in lane_band_ids]

            calibration = LadderCalibration.objects.create(
                analysis=analysis,
                ladder_lane=lane,
                template=template,
                method=result.method,
                coefficients=result.coefficients,
                r_squared=result.r_squared,
                matched_band_count=len(result.band_matches),
                band_matches=[m.to_dict() for m in result.band_matches],
                excluded_band_ids=excluded_for_lane,
                created_by=request.user,
            )

        logger.info(
            f"Created calibration for analysis {pk}",
            user=request.user.username,
            analysis_id=str(pk),
            method=result.method,
            r_squared=result.r_squared,
        )

        # Same logic as api_analysis_calibrate_multi: only report MARKERS
        # GENUINELY MISSING FROM THE GEL (no ladder band assigned to that MW).
        # User-excluded markers are shown in the marker table; flagging them
        # as "not detected" here would be redundant + misleading. Skipped
        # entirely when no template was provided — without a template there
        # is no canonical marker list to compare against.
        unmatched = []
        if template is not None:
            excluded_set = {str(b) for b in excluded_band_ids}
            ladder_assignments = []
            for b in lane.bands.filter(estimated_mw_kda__isnull=False).exclude(estimated_mw_kda=0):
                ladder_assignments.append((str(b.id), round(float(b.estimated_mw_kda), 2)))

            template_bands = list(template.bands.order_by("band_order"))
            for tb in template_bands:
                target_mw = round(float(tb.mw_kda), 2)
                has_active = any(
                    mw == target_mw and band_id not in excluded_set for (band_id, mw) in ladder_assignments
                )
                if has_active:
                    continue
                has_any = any(mw == target_mw for (_, mw) in ladder_assignments)
                if not has_any:
                    unmatched.append({"band_order": tb.band_order, "mw_kda": float(tb.mw_kda)})

        # Expose r_squared + calibrations[] at the top level, mirroring the
        # multi-ladder response shape. The frontend's _updateR2Display reads
        # `result.average_r_squared` first and falls through to
        # `result.r_squared`; previously the single-ladder response had R²
        # only inside `calibration` and `result`, which made the indicator
        # display 0.0000 for valid fits — confusing the user every time.
        result_dict = result.to_dict()
        # Mirror multi-ladder per-calibration entry shape so the marker
        # table + chart code paths can share logic.
        cal_dict = {
            "id": str(calibration.pk),
            "lane_id": str(lane.id),
            "lane_number": lane.lane_number,
            "method": calibration.method,
            "method_display": calibration.get_method_display(),
            "coefficients": calibration.coefficients,
            "r_squared": calibration.r_squared,
            "matched_band_count": calibration.matched_band_count,
            "band_matches": calibration.band_matches,
            "lane_top": lane.y,
            "lane_bottom": lane.y + lane.height,
        }

        return JsonResponse(
            {
                "success": True,
                "r_squared": calibration.r_squared,
                "average_r_squared": calibration.r_squared,
                "calibration": cal_dict,
                "calibrations": [cal_dict],
                "result": result_dict,
                "unmatched_template_bands": unmatched,
                "warnings": result.warnings,
            }
        )

    except Exception as e:
        logger.exception(f"Error creating calibration: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_analysis_apply_calibration(request, pk):
    """
    POST: Apply calibration to estimate MW for all sample bands.

    Updates estimated_mw_kda for all bands in non-ladder lanes.

    Returns:
    - success: boolean
    - bands_updated: Number of bands updated
    """
    from gel_analyzer.services.calibration import CalibrationService

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    # Get calibration (first/only for single-ladder mode)
    calibration = analysis.ladder_calibrations.first()
    if not calibration:
        return json_error("No calibration exists for this analysis", 400)

    try:
        service = CalibrationService()
        updated = service.apply_calibration_to_bands(analysis, calibration)

        logger.info(
            f"Applied calibration to {updated} bands",
            user=request.user.username,
            analysis_id=str(pk),
            bands_updated=updated,
        )

        return JsonResponse(
            {
                "success": True,
                "bands_updated": updated,
            }
        )

    except Exception as e:
        logger.exception(f"Error applying calibration: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["GET", "DELETE"])
def api_analysis_calibration(request, pk):
    """
    GET: Get existing calibration for analysis.
    DELETE: Remove calibration from analysis.
    """

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if request.method == "GET":
        # Get first calibration (for single-ladder backwards compatibility)
        calibration = analysis.ladder_calibrations.select_related("template", "ladder_lane").first()
        if not calibration:
            return JsonResponse({"calibration": None})

        return JsonResponse(
            {
                "calibration": {
                    "id": str(calibration.pk),
                    "ladder_lane_id": calibration.ladder_lane_id,
                    "template_id": str(calibration.template_id) if calibration.template_id else None,
                    "template_name": calibration.template.name if calibration.template else None,
                    "method": calibration.method,
                    "method_display": calibration.get_method_display(),
                    "coefficients": calibration.coefficients,
                    "r_squared": calibration.r_squared,
                    "r_squared_quality": calibration.r_squared_quality,
                    "matched_band_count": calibration.matched_band_count,
                    "band_matches": calibration.band_matches,
                    "excluded_band_ids": calibration.excluded_band_ids or [],
                    "ladder_x_position": calibration.ladder_x_position,
                    "created_at": calibration.created_at.isoformat(),
                },
            }
        )

    elif request.method == "DELETE":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        try:
            # Delete all calibrations (for multi-ladder mode)
            deleted_count = analysis.ladder_calibrations.all().delete()[0]

            logger.info(
                f"Deleted {deleted_count} calibration(s) for analysis {pk}",
                user=request.user.username,
                analysis_id=str(pk),
            )

            return JsonResponse({"success": True, "deleted_count": deleted_count})

        except Exception as e:
            logger.exception(f"Error deleting calibration: {e}")
            return json_error("An unexpected error occurred. Please try again.")


# =============================================================================
# Multi-Ladder Calibration API
# =============================================================================


@login_required
@require_http_methods(["POST"])
def api_analysis_calibrate_multi(request, pk):
    """
    POST: Calibrate all ladder lanes with the same template.

    This enables gel smile correction by computing calibration curves
    for each ladder lane and storing X positions for interpolation.

    Body:
    - template_id: UUID of ladder template (required)
    - method: Calibration method (LOG_LINEAR, POLYNOMIAL_2, POLYNOMIAL_3)

    Returns:
    - success: boolean
    - ladder_count: Number of ladders calibrated
    - calibrations: Array of calibration results
    - errors: Array of error messages for failed ladders
    - average_r_squared: Average R² across all calibrations
    """
    from gel_analyzer.models import LadderTemplate
    from gel_analyzer.services.calibration import MultiLadderCalibrationService

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    template_id = data.get("template_id")
    method = data.get("method", "LOG_LINEAR")
    excluded_band_ids = data.get("excluded_band_ids") or []
    if not isinstance(excluded_band_ids, list):
        return json_error("excluded_band_ids must be a list of band UUIDs")

    # Template is OPTIONAL — see api_analysis_calibrate for the full reasoning.
    # When ladder bands already carry MW values from the Band Editor, the fit
    # uses those directly and never touches the template.
    template = None
    if template_id:
        template = get_object_or_404(LadderTemplate, pk=template_id)

    try:
        service = MultiLadderCalibrationService(analysis)
        result = service.calibrate_all_ladders(
            user=request.user, template=template, method=method, excluded_band_ids=excluded_band_ids
        )

        logger.info(
            f"Multi-ladder calibration for analysis {pk}",
            user=request.user.username,
            analysis_id=str(pk),
            ladder_count=result.ladder_count,
            average_r_squared=result.average_r_squared,
        )

        # Determine unmatched template bands — only flag MARKERS THAT ARE
        # GENUINELY MISSING FROM THE GEL, i.e. the user has not annotated
        # any ladder band with that MW. Markers the user explicitly excluded
        # via the marker checkbox shouldn't show up here: the user already
        # knows about them (they unchecked them) and reporting them as "not
        # detected" is misleading. The exclusion is reflected in the marker
        # table itself.
        # Skip the unmatched-markers report entirely when no template was
        # provided — without a canonical marker list there is nothing to
        # compare against.
        unmatched = []
        if result.calibrations and template is not None:
            template_bands = list(template.bands.order_by("band_order"))
            excluded_set = {str(b) for b in excluded_band_ids}

            ladder_assignments = []  # [(band_id, mw_rounded), ...]
            for ll in analysis.lanes.filter(lane_type="LADDER").prefetch_related("bands"):
                for b in ll.bands.all():
                    if b.estimated_mw_kda and b.estimated_mw_kda > 0:
                        ladder_assignments.append((str(b.id), round(float(b.estimated_mw_kda), 2)))

            for tb in template_bands:
                target_mw = round(float(tb.mw_kda), 2)
                has_active_assignment = any(
                    mw == target_mw and band_id not in excluded_set for (band_id, mw) in ladder_assignments
                )
                if has_active_assignment:
                    continue  # marker is fitted on at least one ladder
                has_any_assignment = any(mw == target_mw for (_, mw) in ladder_assignments)
                if not has_any_assignment:
                    # Truly absent from the gel — worth telling the user.
                    unmatched.append({"band_order": tb.band_order, "mw_kda": float(tb.mw_kda)})

        return JsonResponse(
            {
                "success": result.success,
                "ladder_count": result.ladder_count,
                "template_id": result.template_id,
                "template_name": result.template_name,
                "calibrations": [c.to_dict() for c in result.calibrations],
                "errors": result.errors,
                "average_r_squared": (
                    round(result.average_r_squared, 6) if result.average_r_squared is not None else None
                ),
                "unmatched_template_bands": unmatched,
                "warnings": result.warnings,
            }
        )

    except Exception as e:
        logger.exception(f"Error in multi-ladder calibration: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_analysis_apply_multi_calibration(request, pk):
    """
    POST: Apply multi-ladder calibration to all sample bands.

    Uses position-aware interpolation between ladder lanes to
    estimate MW for each band, correcting for gel smile effect.

    Returns:
    - success: boolean
    - bands_updated: Number of bands with MW estimates
    - bands_failed: Number of bands that failed
    - bands_total: Total bands processed
    """
    from gel_analyzer.services.calibration import MultiLadderCalibrationService

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    try:
        service = MultiLadderCalibrationService(analysis)
        stats = service.apply_calibration_to_all_bands(request.user)

        if stats["bands_updated"] == 0 and stats["bands_total"] > 0:
            return JsonResponse(
                {
                    "success": False,
                    "error_message": "No bands could be calibrated. Check calibration status.",
                    **stats,
                },
                status=400,
            )

        logger.info(
            f"Applied multi-ladder calibration to {stats['bands_updated']} bands",
            user=request.user.username,
            analysis_id=str(pk),
            bands_updated=stats["bands_updated"],
        )

        return JsonResponse(
            {
                "success": True,
                **stats,
            }
        )

    except Exception as e:
        logger.exception(f"Error applying multi-ladder calibration: {e}")
        return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["GET", "DELETE"])
def api_analysis_multi_calibration(request, pk):
    """
    GET: Get multi-ladder calibration status and details.
    DELETE: Remove all calibrations from analysis.

    GET Returns:
    - is_calibrated: boolean
    - ladder_count: Number of calibrated ladders
    - template_id: UUID of template used
    - template_name: Name of template
    - interpolation_method: LINEAR or NEAREST
    - calibrations: Array of calibration data for each ladder

    DELETE Returns:
    - success: boolean
    - deleted_count: Number of calibrations deleted
    """
    from gel_analyzer.services.calibration import MultiLadderCalibrationService

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if request.method == "GET":
        try:
            service = MultiLadderCalibrationService(analysis)
            summary = service.get_calibration_summary()

            return JsonResponse(summary)

        except Exception as e:
            logger.exception(f"Error getting multi-ladder calibration: {e}")
            return json_error("An unexpected error occurred. Please try again.")

    elif request.method == "DELETE":
        if not analysis.is_editable:
            return json_error("Analysis is not editable", 403)

        try:
            service = MultiLadderCalibrationService(analysis)
            deleted_count = service.delete_calibration()

            logger.info(
                f"Deleted {deleted_count} calibrations for analysis {pk}",
                user=request.user.username,
                analysis_id=str(pk),
            )

            return JsonResponse(
                {
                    "success": True,
                    "deleted_count": deleted_count,
                }
            )

        except Exception as e:
            logger.exception(f"Error deleting multi-ladder calibration: {e}")
            return json_error("An unexpected error occurred. Please try again.")


@login_required
@require_http_methods(["POST"])
def api_band_estimate_mw(request, pk):
    """
    POST: Estimate MW for a specific band using multi-ladder interpolation.

    Useful for real-time MW preview in the UI.

    Body:
    - position_y: Y position of band (required)
    - lane_id: Lane ID to use for X position and bounds (required)

    Returns:
    - estimated_mw_kda: Interpolated MW estimate
    - method: Interpolation method used (SINGLE, LINEAR, EDGE)
    - interpolation_weights: Weights used from each ladder
    - confidence: Confidence factor based on R² and distance
    """
    from gel_analyzer.models import Band
    from gel_analyzer.services.calibration import MultiLadderCalibrationService

    band = get_object_or_404(Band, pk=pk)
    analysis = band.lane.analysis

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    # Allow overriding position for preview
    position_y = data.get("position_y", band.position_y) if data else band.position_y

    try:
        service = MultiLadderCalibrationService(analysis)

        # Get lane geometry
        lane = band.lane
        lane_x_center = lane.x + (lane.width // 2)

        result = service.estimate_mw_at_position(
            position_y=position_y,
            lane_x_center=lane_x_center,
            lane_top=lane.y,
            lane_bottom=lane.y + lane.height,
        )

        if result is None:
            return JsonResponse(
                {
                    "estimated_mw_kda": None,
                    "message": "No calibration available",
                }
            )

        return JsonResponse(result.to_dict())

    except Exception as e:
        logger.exception(f"Error estimating MW for band {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.")


# =============================================================================
# SAM Embeddings API
# =============================================================================


@login_required
@require_http_methods(["GET", "POST"])
def api_sam_embeddings(request, pk):
    """
    GET/POST: Get or generate MobileSAM image embeddings for an analysis.

    The embeddings are cached server-side (24h TTL) and sent to the browser
    for use by the MobileSAM decoder worker for band polygon refinement.

    Query params:
    - force: If 'true', regenerate embeddings even if cached

    Returns:
    - image_embedding: Base64-encoded embedding tensor
    - original_size: [height, width] of input image
    - input_size: [height, width] after SAM preprocessing
    - embedding_shape: Shape of embedding tensor [1, 256, 64, 64]
    - cached: Whether the result was served from cache
    """
    analysis = get_object_or_404(GelAnalysis, pk=pk)

    force_refresh = request.GET.get("force", "false").lower() == "true"

    try:
        from gel_analyzer.services.sam import MobileSAMEncoderService

        # Get singleton encoder instance
        encoder = MobileSAMEncoderService.get_instance()

        # Get embeddings (cached or freshly generated)
        embeddings = encoder.get_cached_embeddings(
            gel_image=analysis.gel_image,
            force_refresh=force_refresh,
        )

        # Add metadata
        result = {
            **embeddings,
            "analysis_id": str(analysis.pk),
            "image_id": str(analysis.gel_image.pk),
            "cached": not force_refresh,  # Will be True if cache hit, False if generated
        }

        return JsonResponse(result)

    except ImportError as e:
        logger.error(f"MobileSAM not available: {e}")
        return json_error(
            "MobileSAM is not installed on the server. Contact administrator to install the mobile-sam package.",
            status=503,
        )

    except FileNotFoundError as e:
        logger.error(f"MobileSAM weights not found: {e}")
        return json_error(
            "MobileSAM model weights not found on server. Contact administrator to download mobile_sam.pt.",
            status=503,
        )

    except Exception as e:
        logger.exception(f"Error generating SAM embeddings for analysis {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", status=500)


@login_required
@require_http_methods(["PUT"])
def api_bands_bulk_update_polygons(request):
    """
    Bulk update band polygons after SAM refinement.

    This endpoint is called by the frontend after MobileSAM decoder
    refines band polygons. It updates multiple bands in a single request.

    Request body:
    {
        "updates": [
            {"band_id": "uuid", "polygon": [[x1,y1], [x2,y2], ...]},
            ...
        ]
    }

    Returns:
    {
        "success": True,
        "updated": 5,
        "failed": 0,
        "errors": []
    }
    """
    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    updates = data.get("updates", [])
    if not updates:
        return json_error("No updates provided")

    updated = 0
    failed = 0
    errors = []

    for item in updates:
        band_id = item.get("band_id")
        polygon = item.get("polygon")

        if not band_id:
            failed += 1
            errors.append({"band_id": band_id, "error": "Missing band_id"})
            continue

        if not polygon or not isinstance(polygon, list):
            failed += 1
            errors.append({"band_id": band_id, "error": "Invalid polygon"})
            continue

        try:
            band = Band.objects.select_related("lane__analysis").get(pk=band_id)

            # Check if analysis is editable
            if not band.lane.analysis.is_editable:
                failed += 1
                errors.append({"band_id": band_id, "error": "Analysis not editable"})
                continue

            # Update polygon
            band.polygon = polygon
            band.detection_source = Band.DetectionSource.SAM

            # Recalculate bbox from polygon if valid
            if len(polygon) >= 3:
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                band.bbox_x = min(xs)
                band.bbox_y = min(ys)
                band.bbox_width = max(xs) - band.bbox_x
                band.bbox_height = max(ys) - band.bbox_y

            band.save()
            updated += 1

        except Band.DoesNotExist:
            failed += 1
            errors.append({"band_id": band_id, "error": "Band not found"})

        except Exception:
            logger.exception(f"Error updating polygon for band {band_id}")
            failed += 1
            errors.append({"band_id": band_id, "error": "Processing failed"})

    logger.info(
        f"Bulk polygon update: {updated} updated, {failed} failed",
        user=request.user.username,
        updated=updated,
        failed=failed,
    )

    return JsonResponse(
        {
            "success": True,
            "updated": updated,
            "failed": failed,
            "errors": errors if errors else None,
        }
    )


# =========================================================
# Comparison API Endpoints
# =========================================================


@login_required
@require_http_methods(["GET"])
def api_lane_comparison_data(request, pk):
    """
    The comparison item of one lane, for the "Add Sample" wizard.

    The very item the comparison page builds (``services/comparison_items.lane_item`` then ``enrich``):
    geometry, bands with densitometry, profile, MW calibration, comparability, sample, condition and
    load, the assay and kind it is compared in, and its readout cells. This view used to keep a hand
    copy that had lost the purity, the condition and the load.
    """
    try:
        lane = get_object_or_404(
            Lane.objects.select_related(
                "analysis__gel_image",
                "densitometry_summary",
            ).prefetch_related(
                "bands__densitometry",
                "bands__quant_point",
                "analysis__ladder_calibrations__template",
                "analysis__quant_calibrations",
            ),
            pk=pk,
        )
        item = lane_item(lane)
        enrich([item])
        return JsonResponse(item)

    except Exception as e:
        logger.exception(f"Error in api_lane_comparison_data for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", status=500)


@login_required
@require_http_methods(["GET"])
def api_images_with_densitometry(request):
    """
    List gel images that have densitometry analysis data available.

    Used by the Sample Comparison modal for gel-first selection workflow.
    Returns paginated list of gel images with analysis metadata.

    GET /api/images/with-densitometry/

    Query params:
    - search: text search (filename, analysis name)
    - gel_type: filter by gel type (SDS-PAGE, WESTERN_BLOT, DOT_BLOT)
    - date_from: filter by uploaded date (YYYY-MM-DD)
    - date_to: filter by uploaded date (YYYY-MM-DD)
    - page: page number (default 1)
    - page_size: items per page (default 24, max 100)
    """
    from django.core.paginator import EmptyPage, Paginator
    from django.db.models import Exists, OuterRef, Q
    from django.urls import reverse

    from gel_analyzer.models import LaneDensitometrySummary

    try:
        # Base query: images with at least one analysis that has densitometry data
        images = (
            GelImage.objects.filter(
                Exists(LaneDensitometrySummary.objects.filter(lane__analysis__gel_image=OuterRef("pk")))
            )
            .select_related()
            .prefetch_related("analyses__lanes", "analyses__ladder_calibrations__template")
            .distinct()
        )

        # Apply filters
        search = request.GET.get("search", "").strip()
        if search:
            images = images.filter(
                Q(original_filename__icontains=search) | Q(analyses__name__icontains=search)
            ).distinct()

        gel_type = request.GET.get("gel_type", "").strip()
        if gel_type:
            images = images.filter(gel_type=gel_type)

        date_from = request.GET.get("date_from", "").strip()
        if date_from:
            try:
                from datetime import datetime

                dt = datetime.strptime(date_from, "%Y-%m-%d")
                images = images.filter(uploaded_at__gte=dt)
            except ValueError:
                pass

        date_to = request.GET.get("date_to", "").strip()
        if date_to:
            try:
                from datetime import datetime

                dt = datetime.strptime(date_to, "%Y-%m-%d")
                images = images.filter(uploaded_at__lte=dt)
            except ValueError:
                pass

        # Order by most recent first
        images = images.order_by("-uploaded_at")

        # Pagination
        try:
            page = int(request.GET.get("page", 1))
            page_size = min(int(request.GET.get("page_size", 24)), 100)
        except ValueError:
            page = 1
            page_size = 24

        paginator = Paginator(images, page_size)
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # Build results
        results = []
        for image in page_obj:
            # Get primary analysis with densitometry
            analysis = None
            for a in image.analyses.all():
                if a.lanes.filter(densitometry_summary__isnull=False).exists():
                    analysis = a
                    break

            if not analysis:
                continue

            # Get lane counts
            lanes = list(analysis.lanes.all())
            sample_lanes = [lane for lane in lanes if lane.lane_type == "SAMPLE"]

            # Get calibration info
            calibration = analysis.ladder_calibrations.first()
            has_calibration = calibration is not None
            mw_range = None
            if calibration and calibration.template:
                mw_range = {
                    "min": float(calibration.template.mw_range_min) if calibration.template.mw_range_min else None,
                    "max": float(calibration.template.mw_range_max) if calibration.template.mw_range_max else None,
                }

            # Get thumbnail URL
            thumbnail_url = None
            with contextlib.suppress(Exception):
                thumbnail_url = reverse("gel_analyzer:api_image_proxy", kwargs={"pk": image.pk})

            results.append(
                {
                    "id": str(image.pk),
                    "thumbnail_url": thumbnail_url,
                    "original_filename": image.original_filename,
                    "gel_type": image.gel_type,
                    "gel_type_display": (
                        image.get_gel_type_display() if hasattr(image, "get_gel_type_display") else image.gel_type
                    ),
                    "uploaded_at": image.uploaded_at.isoformat() if image.uploaded_at else None,
                    "analysis": {
                        "id": str(analysis.pk),
                        "name": analysis.name,
                        "lane_count": len(lanes),
                        "sample_lane_count": len(sample_lanes),
                        "has_calibration": has_calibration,
                        "mw_range": mw_range,
                    },
                }
            )

        # Build pagination URLs
        base_url = request.path
        params = request.GET.copy()

        next_url = None
        if page_obj.has_next():
            params["page"] = page_obj.next_page_number()
            next_url = f"{base_url}?{params.urlencode()}"

        prev_url = None
        if page_obj.has_previous():
            params["page"] = page_obj.previous_page_number()
            prev_url = f"{base_url}?{params.urlencode()}"

        return JsonResponse(
            {
                "count": paginator.count,
                "page": page,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "next": next_url,
                "previous": prev_url,
                "results": results,
            }
        )

    except Exception as e:
        logger.exception(f"Error in api_images_with_densitometry: {e}")
        return json_error("An unexpected error occurred. Please try again.", status=500)


# =========================================================
# Analysis Status Workflow API
# =========================================================


@login_required
@require_http_methods(["POST"])
def api_analysis_status_transition(request, pk):
    """
    POST: Transition analysis status.

    Body:
    - action: "complete" | "approve" | "reject" | "reopen"
    - reason: str (required for reject)

    Who may do what lives in ``services/analysis_status.py``, shared with the REST API's
    ``GelAnalysisViewSet.status_transition``:
    - complete: IN_PROGRESS → COMPLETED (creator only)
    - approve: COMPLETED → APPROVED (staff or Gel QA Team)
    - reject: COMPLETED → REJECTED (staff or Gel QA Team, reason required)
    - reopen: REJECTED → IN_PROGRESS (creator only, clears rejection_reason)
    """
    from gel_analyzer.services.analysis_status import PAGE_ACTIONS, StatusChangeRefused, apply_status_action

    analysis = get_object_or_404(GelAnalysis, pk=pk)
    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    action = data.get("action")
    if action not in PAGE_ACTIONS:
        return json_error(f"Invalid action: {action}. Must be one of: {', '.join(PAGE_ACTIONS)}")

    try:
        apply_status_action(analysis, action, request.user, reason=data.get("reason", ""))
    except StatusChangeRefused as exc:
        return json_error(str(exc), status=exc.http_status)

    return JsonResponse(
        {
            "success": True,
            "status": analysis.status,
            "status_display": analysis.get_status_display(),
        }
    )


@login_required
@require_http_methods(["POST"])
def api_readout_reference(request, pk):
    """
    POST: Set (or clear) the reference lane of an anti-HCP western, then republish its readouts.

    Body: ``{"lane_id": <int> | null}``. Every lane's HCP signal is also given in % of the reference
    lane's (spec 2026-10-02-gel-assays-readouts-design.md §4.2); changing it changes every
    published percentage, so the analysis is republished here (``services/readout_publisher.py``).

    Writers only (``access.user_can_write_gel_analyzer``), and only while the analysis is editable,
    like the lane and band endpoints. 400 when ``lane_id`` is not an integer or names a lane of
    another analysis.

    Returns ``{"success", "reference_lane_id", "reference_lane_number", "published": <counts>}``.
    """
    from gel_analyzer.services.readout_publisher import publish_gel_readouts

    if not user_can_write_gel_analyzer(request.user):
        return json_error("You are not allowed to modify gel data.", 403)

    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image__assay"), pk=pk)
    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if not isinstance(data, dict) or "lane_id" not in data:
        return json_error('Body must be {"lane_id": <lane id> | null}')

    lane_id = data["lane_id"]
    lane = None
    if lane_id is not None:
        # bool is an int subclass: {"lane_id": true} must not name lane 1.
        if isinstance(lane_id, bool) or not isinstance(lane_id, int):
            return json_error("lane_id must be an integer or null")
        lane = analysis.lanes.filter(pk=lane_id).first()
        if lane is None:
            return json_error(f"Lane {lane_id} is not a lane of this analysis")

    analysis.readout_reference_lane = lane
    analysis._change_reason = (
        f"HCP reference lane set to lane {lane.lane_number}" if lane else "HCP reference lane cleared"
    )
    analysis.save(update_fields=["readout_reference_lane", "updated_at"])

    published = publish_gel_readouts(analysis)

    logger.info(
        "Readout reference lane changed",
        user=request.user.username,
        analysis_id=str(analysis.pk),
        reference_lane_id=lane.pk if lane else None,
        published=published.get("published"),
    )

    return JsonResponse(
        {
            "success": True,
            "reference_lane_id": lane.pk if lane else None,
            "reference_lane_number": lane.lane_number if lane else None,
            "published": published,
        }
    )


@login_required
@require_http_methods(["POST"])
def api_crop_image(request, pk):
    """
    POST: Crop a gel image to the specified rectangle.

    Body: { x: int, y: int, width: int, height: int }
    All values are in display-space pixels.

    Guards:
    - Image must exist.
    - No analysis on this image may have lanes (would invalidate coords).
    - Crop rect must be within image bounds and >= 50x50.

    Returns: { success: true, width: int, height: int }
    """
    from gel_analyzer.services.file_handler import GelFileHandler

    gel_image = get_object_or_404(GelImage, pk=pk)

    # Guard: reject if any analysis on this image has lanes
    analyses_with_lanes = GelAnalysis.objects.filter(gel_image=gel_image, lanes__isnull=False).distinct()
    if analyses_with_lanes.exists():
        details = [f'"{a}" ({a.lanes.count()} lanes)' for a in analyses_with_lanes.select_related("gel_image")[:5]]
        return json_error(
            "Cannot crop: the following analyses on this image still have lanes: "
            + ", ".join(details)
            + ". Remove all lanes from these analyses first.",
            status=400,
        )

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    try:
        x = int(data.get("x", 0))
        y = int(data.get("y", 0))
        width = int(data.get("width", 0))
        height = int(data.get("height", 0))
    except (TypeError, ValueError):
        return json_error("x, y, width, height must be integers")

    log = logger.bind(gel_image_id=str(pk), user=request.user.username, crop=f"{x},{y},{width},{height}")
    log.info("Crop image requested")

    try:
        new_w, new_h = GelFileHandler.crop_image(gel_image, x, y, width, height)
    except ValueError as e:
        log.warning(f"Crop validation failed: {e}")
        return json_error(str(e))
    except Exception as e:
        return json_error(
            public_error_text(log, e, public="The crop failed.", log="Crop failed", request=request), status=500
        )

    log.success(f"Image cropped to {new_w}x{new_h}")
    return JsonResponse(
        {
            "success": True,
            "width": new_w,
            "height": new_h,
        }
    )


@login_required
@require_http_methods(["POST"])
def api_calibrate_detection(request, pk):
    """
    POST: Calibrate band detection parameters from user-marked teaching regions.

    Accepts 3 optional regions (background, small_band, large_band) and derives
    optimal BandDetectionParams. At least one region must be provided.

    Request body:
        {
            "background": {"x": 120, "y": 300, "width": 40, "height": 60, "source": "image"},
            "small_band": {"x": 210, "y": 445, "width": 35, "height": 12, "source": "image"},
            "large_band": {"x": 210, "y": 280, "width": 35, "height": 45, "source": "image"}
        }

    For profile-source regions:
        {"y_start": 300, "y_end": 360, "source": "profile"}

    Returns:
        JSON with derived_params, diagnostics, explanations, and success flag.
    """
    import numpy as np

    from gel_analyzer.services.band_detection.calibration import DetectionCalibrator, TeachingRegion
    from gel_analyzer.services.file_handler import GelFileHandler

    analysis = get_object_or_404(GelAnalysis, pk=pk)
    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON body")

    log = logger.bind(
        analysis_id=str(pk),
        user=request.user.username,
    )
    log.info("Calibrate detection requested")

    # Load image (original 16-bit for maximum dynamic range)
    try:
        img_array = GelFileHandler.load_image_as_array(analysis.gel_image)
    except Exception as e:
        # The exception names the stored file's path on the server: a sentence and a reference instead.
        error = public_error_text(
            log, e, public="The gel image could not be loaded.", log="Failed to load image", request=request
        )
        return json_error(error, status=500)

    # Parse teaching regions
    min_region_size = 5

    def parse_region(region_data, name):
        if not region_data:
            return None

        source = region_data.get("source", "image")

        if source == "profile":
            y_start = int(region_data.get("y_start", 0))
            y_end = int(region_data.get("y_end", 0))
            if abs(y_end - y_start) < min_region_size:
                return None
            y_lo, y_hi = min(y_start, y_end), max(y_start, y_end)
            # Extract a vertical strip from the image center
            cx = img_array.shape[1] // 2
            half_w = max(10, img_array.shape[1] // 10)
            roi = img_array[y_lo:y_hi, max(0, cx - half_w) : min(img_array.shape[1], cx + half_w)]
            return TeachingRegion(
                intensities=roi.ravel().astype(np.float64),
                x=max(0, cx - half_w),
                y=y_lo,
                width=half_w * 2,
                height=y_hi - y_lo,
                source="profile",
            )

        # Image source
        try:
            x = int(region_data.get("x", 0))
            y = int(region_data.get("y", 0))
            width = int(region_data.get("width", 0))
            height = int(region_data.get("height", 0))
        except (TypeError, ValueError):
            log.warning(f"Invalid {name} region coordinates")
            return None

        if width < min_region_size or height < min_region_size:
            log.warning(f"{name} region too small: {width}x{height}")
            return None

        return TeachingRegion(
            intensities=np.array([], dtype=np.float64),
            x=x,
            y=y,
            width=width,
            height=height,
            source="image",
        )

    background = parse_region(data.get("background"), "background")
    small_band = parse_region(data.get("small_band"), "small_band")
    large_band = parse_region(data.get("large_band"), "large_band")

    if not background and not small_band and not large_band:
        return json_error("At least one teaching region must be provided.")

    # Run calibration
    try:
        calibrator = DetectionCalibrator(img_array)
        result = calibrator.calibrate(background, small_band, large_band)
    except Exception as e:
        return json_error(
            public_error_text(log, e, public="The calibration failed.", log="Calibration failed", request=request),
            status=500,
        )

    if not result.success:
        log.warning(f"Calibration unsuccessful: {result.error}")
        return json_error(result.error)

    log.success(f"Calibration complete: {len(result.explanations)} explanations")
    return JsonResponse(
        {
            "success": True,
            "derived_params": result.params.to_dict(),
            "diagnostics": result.diagnostics,
            "explanations": result.explanations,
        }
    )


# ============================================================================
# CV2 Vision Band Detection API
# ============================================================================


@login_required
@require_http_methods(["POST"])
def api_detect_bands_cv2_lane(request, pk):
    """POST: CV2 vision detection in a single lane (preview mode)."""
    from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
    from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    params_dict = data.get("params", data) if data else {}
    bg_type_override = data.get("bg_type") if data else None

    try:
        try:
            params = CV2DetectionParams.from_dict(params_dict)
        except ValueError as e:  # the params' own range check (cv2_params.py)
            logger.warning(f"Invalid CV2 detection params: {e}")
            return json_error(f"Invalid parameters: {e}")
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)

        b = lane.bbox
        x, y, w, h = b["x"], b["y"], b["width"], b["height"]
        lane_crop = image[y : y + h, x : x + w]

        detector = CV2BandDetector(params)
        bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h), bg_type_override=bg_type_override)

        response = {
            "success": True,
            "lane_id": lane.pk,
            "lane_number": lane.lane_number,
            "bands": [band.to_dict() for band in bands],
            "band_count": len(bands),
            "params_used": params.to_dict(),
        }

        logger.info(
            f"CV2 detection preview for lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            band_count=len(bands),
        )
        return JsonResponse(response)

    except Exception as e:  # a ValueError from the detection itself carries numpy's or OpenCV's text
        error = public_error_text(
            logger,
            e,
            public="The band detection failed.",
            log=f"CV2 band detection failed for lane {pk}",
            request=request,
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_cv2_lane_save(request, pk):
    """POST: CV2 vision detection in a single lane — save to DB."""
    from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
    from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)
    analysis = lane.analysis

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    params_dict = data.get("params", data) if data else {}
    delete_existing = data.get("delete_existing", True) if data else True
    bg_type_override = data.get("bg_type") if data else None

    try:
        try:
            params = CV2DetectionParams.from_dict(params_dict)
        except ValueError as e:  # the params' own range check (cv2_params.py)
            logger.warning(f"Invalid CV2 detection params: {e}")
            return json_error(f"Invalid parameters: {e}")
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        b = lane.bbox
        x, y, w, h = b["x"], b["y"], b["width"], b["height"]
        lane_crop = image[y : y + h, x : x + w]

        detector = CV2BandDetector(params)
        bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h), bg_type_override=bg_type_override)

        if delete_existing:
            Band.objects.filter(
                lane=lane,
                detection_source=Band.DetectionSource.CV2_VISION,
            ).delete()

        band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

        for i, detected in enumerate(bands, 1):
            Band.objects.create(
                lane=lane,
                band_number=i,
                position_y=detected.position_y,
                bbox_x=detected.bbox_x,
                bbox_y=detected.bbox_y,
                bbox_width=detected.bbox_width,
                bbox_height=detected.bbox_height,
                polygon=detected.polygon,
                confidence=detected.confidence,
                detection_source=Band.DetectionSource.CV2_VISION,
                band_type=band_type,
                intensity_raw=detected.intensity_raw,
                intensity_peak=detected.intensity_peak,
                area_pixels=detected.area_pixels,
                created_by=request.user,
            )

        analysis.update_counts()

        saved_bands = lane.bands.filter(
            detection_source=Band.DetectionSource.CV2_VISION,
        ).order_by("position_y")

        logger.info(
            f"Saved {len(bands)} CV2 bands for lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            band_count=len(bands),
        )

        return JsonResponse(
            {
                "success": True,
                "bands": [band_to_dict(b) for b in saved_bands],
                "band_count": len(bands),
                "created_count": len(bands),
            }
        )

    except Exception as e:  # a ValueError from the detection itself carries numpy's or OpenCV's text
        error = public_error_text(
            logger,
            e,
            public="The band detection failed.",
            log=f"CV2 band detection save failed for lane {pk}",
            request=request,
        )
        return json_error(error, 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_cv2_calibrate(request, pk):
    """POST: Return auto-calibrated CV2 params for this analysis image."""
    import numpy as np

    from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    analysis = get_object_or_404(GelAnalysis, pk=pk)
    image = GelFileHandler.load_image_as_array(analysis.gel_image)

    lanes = analysis.lanes.all()
    if lanes.exists():
        heights = [lane.bbox["height"] for lane in lanes]
        lane_height = int(np.median(heights))
    else:
        lane_height = image.shape[0]

    params = CV2DetectionParams.auto_calibrate(image, lane_height)

    # Detect background type — prefer using a ladder lane (least loaded)
    # otherwise fall back to full image
    from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector

    detector = CV2BandDetector(params)
    gray = detector._normalize_to_uint8(image)

    # Try to find a ladder lane for polarity detection (least loaded)
    ladder_lanes = [lane for lane in lanes if lane.lane_type == "LADDER"] if lanes.exists() else []
    if ladder_lanes:
        lb = ladder_lanes[0].bbox
        lane_crop = gray[lb["y"] : lb["y"] + lb["height"], lb["x"] : lb["x"] + lb["width"]]
        profile = detector._extract_profile(lane_crop)
    else:
        profile = detector._extract_profile(gray)

    profile = detector._smooth_profile(profile, params.block_size)
    bg_type = detector._detect_polarity(profile)

    return JsonResponse(
        {
            "success": True,
            "params": params.to_dict(),
            "bg_type": bg_type,
            "lane_height_used": lane_height,
            "image_shape": list(image.shape),
        }
    )


@login_required
@require_http_methods(["POST"])
def api_detect_bands_cv2_async(request, pk):
    """POST: Start async CV2 band detection for an analysis."""
    from gel_analyzer.tasks import detect_bands_cv2_bulk_task

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    params_dict = data.get("params", data) if data else {}
    raw_lane_ids = data.get("lane_ids") if data else None
    save_results = data.get("save_results", False) if data else False
    bg_type = data.get("bg_type") if data else None

    lane_ids = None
    if raw_lane_ids:
        lane_ids = []
        for lid in raw_lane_ids:
            with contextlib.suppress(ValueError, TypeError):
                lane_ids.append(int(lid))
        if not lane_ids:
            return json_error("No valid lane IDs provided. Save annotations first.", 400)

    if save_results and not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    try:
        task = detect_bands_cv2_bulk_task.delay(
            analysis_id=str(pk),
            lane_ids=lane_ids,
            params_dict=params_dict,
            user_id=request.user.pk if save_results else None,
            save_results=save_results,
            bg_type=bg_type,
        )
    except Exception:
        logger.exception(f"Failed to start async CV2 detection task for analysis {pk}")
        return json_error(
            "Could not start background task. The task queue may be unavailable.",
            status=503,
        )

    logger.info(
        f"Started async CV2 band detection task {task.id}",
        user=request.user.username,
        analysis_id=str(pk),
        save_results=save_results,
    )

    return JsonResponse(
        {
            "success": True,
            "task_id": task.id,
            "analysis_id": str(pk),
            "message": "CV2 band detection task started",
        }
    )


# ── Hybrid Band Detection API ─────────────────────────────────────────


# ---------------------------------------------------------------------------
# Cross-Lane Consensus API (POST run / DELETE undo)
# ---------------------------------------------------------------------------
