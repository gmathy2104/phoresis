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
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.forms import band_to_dict, lane_to_dict
from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def json_error(message: str, status: int = 400) -> JsonResponse:
    """Return a JSON error response."""
    return JsonResponse({"error": message}, status=status)


def parse_json_body(request) -> dict | None:
    """Parse JSON body from request. Returns None on decode failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None


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
                protein_load_type=data.get("protein_load_type", ""),
                # Sample info
                sample_name=data.get("sample_name", ""),
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
    PUT: Update lane properties.
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
            "protein_load_type",
            "sample_name",
            "notes",
        ]
        for field in updatable_fields:
            if field in data:
                setattr(lane, field, data[field])

        # Handle ladder_template_id (FK for LADDER lanes)
        if "ladder_template_id" in data:
            lane.ladder_template_id = data["ladder_template_id"]

        lane.save()

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
    """
    lane = get_object_or_404(Lane.objects.select_related("analysis"), pk=pk)
    analysis = lane.analysis

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    try:
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

        band = Band.objects.create(
            lane=lane,
            detection_source="MANUAL",
            band_type=data.get("band_type", default_band_type),
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

    except Exception as e:
        logger.exception(f"Error creating band: {e}")
        return json_error("An unexpected error occurred. Please try again.")


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
    PUT: Update band properties.
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

        band.save()

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
@require_http_methods(["GET"])
def api_analysis_data(request, pk):
    """
    GET: Get full analysis data with all lanes and bands.

    Used to load the initial state of the annotation viewer.
    """
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)

    # Prefetch all lanes and bands
    lanes = analysis.lanes.prefetch_related("bands").order_by("lane_number")

    return JsonResponse(
        {
            "analysis": {
                "id": str(analysis.pk),
                "name": analysis.name,
                "status": analysis.status,
                "is_editable": analysis.is_editable,
                "total_lanes": analysis.total_lanes,
                "total_bands": analysis.total_bands,
            },
            "gel_image": {
                "id": str(analysis.gel_image.pk),
                "url": analysis.gel_image.display_file.url if analysis.gel_image.display_file else None,
                "width": analysis.gel_image.width,
                "height": analysis.gel_image.height,
                "gel_type": analysis.gel_image.gel_type,
            },
            "lanes": [lane_to_dict(lane) for lane in lanes],
        }
    )


@login_required
@require_http_methods(["GET"])
def api_image_proxy(request, pk):
    """
    Proxy endpoint for gel image files.

    Serves the image through Django to avoid CORS issues when images
    are stored on external storage (e.g., Azure Blob Storage).

    This is used by the auto-detect and auto-enhance features which need to read
    pixel data from the canvas, which would otherwise fail due to
    CORS tainted canvas restrictions.
    """
    gel_image = get_object_or_404(GelImage, pk=pk)

    # Prefer display_file, fallback to original_file
    image_file = gel_image.display_file or gel_image.original_file
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
        # No caching — image may be replaced by crop
        response["Cache-Control"] = "private, no-cache"

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
        "protein_load_type",
        "sample_name",
        "notes",
    ]

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

                old_x = lane.x

                # Update allowed fields
                for field in updatable_fields:
                    if field in lane_data:
                        setattr(lane, field, lane_data[field])

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
    from gel_analyzer.services.band_detection import (
        BandDetectionParams,
        BandDetectionService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}

    try:
        # Build params from request
        params = BandDetectionParams.from_dict(params_dict)

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

    except ValueError as e:
        logger.warning(f"Invalid detection params: {e}")
        return json_error(f"Invalid parameters: {e}")

    except Exception as e:
        logger.exception(f"Band detection failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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
        logger.exception(f"Detection diagnostic failed for lane {pk}: {e}")
        return json_error(f"Diagnostic failed: {e}", 500)


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
    from gel_analyzer.services.band_detection import (
        BandDetectionParams,
        BandDetectionService,
    )
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
        # Build params from request
        params = BandDetectionParams.from_dict(params_dict)

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

    except ValueError as e:
        logger.warning(f"Invalid detection params: {e}")
        return json_error(f"Invalid parameters: {e}")

    except Exception as e:
        logger.exception(f"Band detection failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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
    from gel_analyzer.services.band_detection import (
        BandDetectionParams,
        BandDetectionService,
    )
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
        # Build params from request
        params = BandDetectionParams.from_dict(params_dict)

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

    except ValueError as e:
        logger.warning(f"Invalid detection params: {e}")
        return json_error(f"Invalid parameters: {e}")

    except Exception as e:
        logger.exception(f"Bulk band detection failed for analysis {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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


@login_required
@require_http_methods(["POST"])
def api_detect_peaks_from_profile(request, pk):
    """
    POST: Detect peaks from lane intensity profile.

    Uses AdvancedPeakDetector from densitometry services to detect
    peaks in the intensity profile. Can run in preview mode or save bands.

    Body:
    - params: Detection parameters dict
        - sensitivity: float (0.5-1.0, default 0.85)
        - min_peak_distance: int (pixels, default 10)
        - match_tolerance_px: int (pixels, default 15)
        - smoothing_window: int (default 11)
        - enable_deconvolution: bool (default False)
        - enable_shoulder_detection: bool (default True)
    - preview: bool (default True) - if True, return peaks without saving

    Returns:
    - success: boolean
    - peaks: Array of detected peaks with y_position, height, width, is_orphan
    - total_peaks: int
    - orphan_count: int (peaks not matching existing bands)
    - matched_count: int (peaks matching existing bands)
    - bands_created: int (if preview=False)
    """
    from gel_analyzer.services.band_detection import BandDetectionParams
    from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
    from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor
    from gel_analyzer.services.densitometry import (
        AdvancedPeakDetector,
        PeakDeconvolutionService,
        PeakDetectionParams,
        PeakMatchingService,
    )
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image").prefetch_related("bands"), pk=pk)
    analysis = lane.analysis

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    # Support both flat params and wrapped {params: {...}} format
    params_dict = data.get("params", data) if data else {}
    preview = data.get("preview", True) if data else True

    if not preview and not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    try:
        # Build detection params
        detection_params = PeakDetectionParams.from_dict(params_dict)

        # Load image and extract profile
        image = GelFileHandler.load_image_as_array(analysis.gel_image)
        band_params = BandDetectionParams(
            smoothing_window=params_dict.get("smoothing_window", 11),
        )

        extractor = IntensityProfileExtractor(band_params)
        processor = ProfileProcessor(band_params)

        profile = extractor.extract_profile(image, lane)
        profile = processor.process(profile)

        # Detect peaks
        detector = AdvancedPeakDetector(detection_params)
        peaks = detector.detect_peaks(profile)

        # Optionally deconvolve
        if detection_params.enable_deconvolution and peaks:
            deconv_service = PeakDeconvolutionService()
            peaks = deconv_service.deconvolve_wide_peaks(
                profile, peaks, width_threshold=detection_params.deconvolution_threshold_px
            )

        # Get existing bands for matching
        existing_bands = list(lane.bands.all())
        match_tolerance = params_dict.get("match_tolerance_px", 15)

        # Match peaks to bands
        matching_service = PeakMatchingService(tolerance_px=match_tolerance)
        result = matching_service.match_peaks_to_bands(peaks, existing_bands, lane.id)

        # Create bands if not preview
        bands_created = 0
        if not preview:
            # Determine band type based on lane type (LADDER -> MW_REFERENCE, else OTHER)
            band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

            for peak in result.peaks:
                if peak.is_orphan:
                    Band.objects.create(
                        lane=lane,
                        detection_source="PROFILE",
                        band_type=band_type,
                        position_y=peak.y_position,
                        bbox_x=lane.x,
                        bbox_y=max(0, peak.y_position - peak.width_px // 2),
                        bbox_width=lane.width,
                        bbox_height=peak.width_px,
                    )
                    bands_created += 1

            # Update analysis counts
            analysis.update_counts()

            logger.info(
                f"Created {bands_created} PROFILE bands for lane {lane.lane_number}",
                user=request.user.username,
                lane_id=pk,
                band_count=bands_created,
            )

        return JsonResponse(
            {
                "success": result.success,
                "peaks": [p.to_dict() for p in result.peaks],
                "total_peaks": result.total_peaks,
                "orphan_count": result.orphan_count,
                "matched_count": result.matched_count,
                "bands_created": bands_created,
            }
        )

    except Exception as e:
        logger.exception(f"Profile peak detection failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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
@require_http_methods(["POST"])
def api_detect_peaks_profile_async(request, pk):
    """
    POST: Start async profile peak detection for an analysis.

    Triggers a Celery task for background processing of multiple lanes.
    Use this for batch detection when processing many lanes.

    Body:
    - lane_ids: Array of lane IDs to process (required)
    - params: Detection parameters dict
        - sensitivity: float (0.5-1.0, default 0.85)
        - min_peak_distance: int (pixels, default 10)
        - match_tolerance_px: int (pixels, default 15)
        - smoothing_window: int (default 11)
        - enable_deconvolution: bool (default False)
        - enable_shoulder_detection: bool (default True)

    Returns:
    - success: boolean
    - task_id: Celery task ID for status polling
    """
    from gel_analyzer.tasks import detect_peaks_profile_bulk_task

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    if not analysis.is_editable:
        return json_error("Analysis is not editable", 403)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    raw_lane_ids = data.get("lane_ids", [])
    if not raw_lane_ids:
        return json_error("lane_ids is required", 400)

    # Filter out temporary frontend IDs (e.g. 'temp_1_...')
    lane_ids = []
    for lid in raw_lane_ids:
        with contextlib.suppress(ValueError, TypeError):
            lane_ids.append(int(lid))
    if not lane_ids:
        return json_error("No valid lane IDs provided. Save annotations first.", 400)

    params_dict = data.get("params", {})

    # Start Celery task
    try:
        task = detect_peaks_profile_bulk_task.delay(
            analysis_id=str(pk),
            lane_ids=lane_ids,
            params_dict=params_dict,
            user_id=request.user.pk,
        )
    except Exception:
        logger.exception(f"Failed to start async profile peak detection task for analysis {pk}")
        return json_error(
            "Could not start background task. The task queue may be unavailable. "
            "Please try the synchronous detection instead.",
            status=503,
        )

    logger.info(
        f"Started async profile peak detection task {task.id}",
        user=request.user.username,
        analysis_id=str(pk),
        lane_count=len(lane_ids),
    )

    return JsonResponse(
        {
            "success": True,
            "task_id": task.id,
            "analysis_id": str(pk),
            "lane_count": len(lane_ids),
            "message": "Profile peak detection task started",
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
    if not template_id:
        return json_error("template_id is required")

    # Get lane and template
    lane = get_object_or_404(Lane.objects.filter(analysis=analysis), pk=lane_id)
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
        # as "not detected" here would be redundant + misleading.
        excluded_set = {str(b) for b in excluded_band_ids}
        ladder_assignments = []
        for b in lane.bands.filter(estimated_mw_kda__isnull=False).exclude(estimated_mw_kda=0):
            ladder_assignments.append((str(b.id), round(float(b.estimated_mw_kda), 2)))

        template_bands = list(template.bands.order_by("band_order"))
        unmatched = []
        for tb in template_bands:
            target_mw = round(float(tb.mw_kda), 2)
            has_active = any(mw == target_mw and band_id not in excluded_set for (band_id, mw) in ladder_assignments)
            if has_active:
                continue
            has_any = any(mw == target_mw for (_, mw) in ladder_assignments)
            if not has_any:
                unmatched.append({"band_order": tb.band_order, "mw_kda": float(tb.mw_kda)})

        return JsonResponse(
            {
                "success": True,
                "calibration": {
                    "id": str(calibration.pk),
                    "method": calibration.method,
                    "method_display": calibration.get_method_display(),
                    "coefficients": calibration.coefficients,
                    "r_squared": calibration.r_squared,
                    "matched_band_count": calibration.matched_band_count,
                    "band_matches": calibration.band_matches,
                },
                "result": result.to_dict(),
                "unmatched_template_bands": unmatched,
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

    if not template_id:
        return json_error("template_id is required")

    template = get_object_or_404(LadderTemplate, pk=template_id)

    try:
        service = MultiLadderCalibrationService(analysis)
        result = service.calibrate_all_ladders(
            template,
            request.user,
            method,
            excluded_band_ids=excluded_band_ids,
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
        unmatched = []
        if result.calibrations:
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
                "average_r_squared": round(result.average_r_squared, 6)
                if result.average_r_squared is not None
                else None,
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


def _get_comparability_message(issues: list) -> str:
    """
    Generate a user-friendly message for comparability issues.

    Args:
        issues: List of issue codes

    Returns:
        Human-readable message explaining why lane cannot be compared
    """
    if not issues:
        return ""

    messages = {
        "no_lane": "Lane data is missing",
        "no_gel_image": "Gel image is not available",
        "no_profile": "Profile data has not been computed",
        "no_calibration": "MW calibration is not available",
    }

    parts = [messages.get(issue, f"Unknown issue: {issue}") for issue in issues]
    return ". ".join(parts)


@login_required
@require_http_methods(["GET"])
def api_lane_comparison_data(request, pk):
    """
    Get lane data for comparison view.

    Returns complete lane data including:
    - Lane geometry and metadata
    - Bands with densitometry
    - Profile data for electropherogram
    - MW calibration data
    - Comparability status
    """
    from django.urls import reverse

    try:
        comparability_issues = []

        lane = get_object_or_404(
            Lane.objects.select_related(
                "analysis__gel_image",
                "densitometry_summary",
            ).prefetch_related("bands__densitometry", "analysis__ladder_calibrations__template"),
            pk=pk,
        )

        # Get gel image URL via proxy
        image_url = None
        try:
            if lane.analysis and lane.analysis.gel_image:
                image_url = reverse("gel_analyzer:api_image_proxy", kwargs={"pk": lane.analysis.gel_image.pk})
        except Exception as e:
            logger.warning(f"Error getting gel image URL for lane {pk}: {e}")

        if not image_url:
            comparability_issues.append("no_gel_image")

        # Get profile data
        profile_data = None
        if (
            hasattr(lane, "densitometry_summary")
            and lane.densitometry_summary
            and lane.densitometry_summary.profile_data
        ):
            profile_data = lane.densitometry_summary.profile_data

        if not profile_data:
            comparability_issues.append("no_profile")

        # Get calibration data
        calibration_data = None
        if lane.analysis:
            calibration = lane.analysis.ladder_calibrations.first()
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

        if not calibration_data:
            comparability_issues.append("no_calibration")

        # Pre-compute MW-aligned profile.
        # Rf is computed in the LADDER lane's reference frame — the frame
        # the calibration curve was fit in. Using lane.y / lane.height of
        # the SAMPLE lane here would skew the entire MW axis whenever the
        # sample lane bbox doesn't perfectly match the ladder lane bbox.
        mw_profile_data = None
        if profile_data and calibration_data and lane.analysis:
            try:
                calibration = lane.analysis.ladder_calibrations.first()
                if calibration and calibration.ladder_lane:
                    y_positions = profile_data.get("y_positions", [])
                    intensities = profile_data.get("intensities", [])
                    ladder_top = calibration.ladder_lane.y
                    ladder_bottom = calibration.ladder_lane.y + calibration.ladder_lane.height

                    if y_positions and intensities and ladder_bottom > ladder_top:
                        mw_values = []
                        for y_pos in y_positions:
                            mw = calibration.estimate_mw(int(y_pos), ladder_top, ladder_bottom)
                            mw_values.append(float(mw) if mw else None)

                        mw_profile_data = {
                            "mw_values": mw_values,
                            "intensities": intensities,
                            "y_positions": y_positions,
                        }
            except Exception as e:
                logger.warning(f"Error computing MW profile for lane {pk}: {e}")

        # Serialize bands
        bands_data = []
        for band in lane.bands.all().order_by("position_y"):
            band_info = {
                "id": str(band.pk),
                "band_type": band.band_type,
                "band_type_display": band.get_band_type_display()
                if hasattr(band, "get_band_type_display")
                else band.band_type,
                "position_y": float(band.position_y) if band.position_y else None,
                "estimated_mw_kda": float(band.estimated_mw_kda)
                if hasattr(band, "estimated_mw_kda") and band.estimated_mw_kda
                else None,
                "bbox": {
                    "x": float(band.bbox_x) if hasattr(band, "bbox_x") and band.bbox_x else None,
                    "y": float(band.bbox_y) if hasattr(band, "bbox_y") and band.bbox_y else None,
                    "width": float(band.bbox_width) if hasattr(band, "bbox_width") and band.bbox_width else None,
                    "height": float(band.bbox_height) if hasattr(band, "bbox_height") and band.bbox_height else None,
                },
            }

            if hasattr(band, "densitometry") and band.densitometry:
                d = band.densitometry
                band_info["densitometry"] = {
                    "corrected_area": float(d.corrected_area) if d.corrected_area else None,
                    "relative_percent_lane": float(d.relative_percent_lane) if d.relative_percent_lane else None,
                    "relative_percent_gel": float(d.relative_percent_gel) if d.relative_percent_gel else None,
                    "fit_r_squared": float(d.fit_r_squared) if d.fit_r_squared else None,
                    "peak_amplitude": float(d.peak_amplitude) if d.peak_amplitude else None,
                    "fwhm": float(d.fwhm) if d.fwhm else None,
                }

            bands_data.append(band_info)

        # Build label and source info
        if lane.sample_name:
            label = f"Lane {lane.lane_number}: {lane.sample_name}"
            source = "lane"
            source_id = lane.pk
        else:
            label = f"Lane {lane.lane_number}"
            source = "lane"
            source_id = lane.pk

        # Critical vs soft issues
        critical_issues = [i for i in comparability_issues if i in ("no_lane", "no_gel_image")]

        return JsonResponse(
            {
                "id": f"{source}_{source_id}",
                "source": source,
                "label": label,
                "sample": None,
                "lane": {
                    "id": lane.pk,
                    "lane_number": lane.lane_number,
                    "sample_name": lane.sample_name or None,
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
                "bands": bands_data,
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
                "comparability": {
                    "is_valid": len(critical_issues) == 0,
                    "issues": comparability_issues,
                    "critical_issues": critical_issues,
                    "message": _get_comparability_message(critical_issues) if critical_issues else None,
                },
            }
        )

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
                    "gel_type_display": image.get_gel_type_display()
                    if hasattr(image, "get_gel_type_display")
                    else image.gel_type,
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

    Transition rules:
    - complete: IN_PROGRESS → COMPLETED (creator only)
    - approve: COMPLETED → APPROVED (staff or "Gel QA Team" group)
    - reject: COMPLETED → REJECTED (staff or "Gel QA Team" group, reason required)
    - reopen: REJECTED → IN_PROGRESS (creator only, clears rejection_reason)
    """
    from django.utils import timezone

    analysis = get_object_or_404(GelAnalysis, pk=pk)
    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")

    action = data.get("action")
    reason = data.get("reason", "").strip()

    if action not in ("complete", "approve", "reject", "reopen"):
        return json_error(f"Invalid action: {action}. Must be one of: complete, approve, reject, reopen")

    user = request.user
    is_creator = analysis.created_by == user
    is_qa = user.is_staff or user.groups.filter(name="Gel QA Team").exists()

    # Validate transitions
    if action == "complete":
        if analysis.status != GelAnalysis.Status.IN_PROGRESS:
            return json_error(
                f'Cannot complete analysis in status "{analysis.get_status_display()}". Analysis must be In Progress.'
            )
        if not is_creator:
            return json_error("Only the analysis creator can mark it as complete.", status=403)

        analysis.status = GelAnalysis.Status.COMPLETED
        analysis._change_reason = f"Marked as completed by {user.get_full_name() or user.username}"
        analysis.save(update_fields=["status", "updated_at"])

    elif action == "approve":
        if analysis.status != GelAnalysis.Status.COMPLETED:
            return json_error(
                f'Cannot approve analysis in status "{analysis.get_status_display()}". '
                f"Analysis must be Completed first."
            )
        if not is_qa:
            return json_error("Only staff or Gel QA Team members can approve analyses.", status=403)

        analysis.status = GelAnalysis.Status.APPROVED
        analysis.approved_by = user
        analysis.approved_at = timezone.now()
        analysis._change_reason = f"Approved by {user.get_full_name() or user.username}"
        analysis.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    elif action == "reject":
        if analysis.status != GelAnalysis.Status.COMPLETED:
            return json_error(
                f'Cannot reject analysis in status "{analysis.get_status_display()}". Analysis must be Completed first.'
            )
        if not is_qa:
            return json_error("Only staff or Gel QA Team members can reject analyses.", status=403)
        if not reason:
            return json_error("A reason is required when rejecting an analysis.")

        analysis.status = GelAnalysis.Status.REJECTED
        analysis.rejection_reason = reason
        analysis._change_reason = f"Rejected by {user.get_full_name() or user.username}: {reason}"
        analysis.save(update_fields=["status", "rejection_reason", "updated_at"])

    elif action == "reopen":
        if analysis.status != GelAnalysis.Status.REJECTED:
            return json_error(
                f'Cannot reopen analysis in status "{analysis.get_status_display()}". '
                f"Only rejected analyses can be reopened."
            )
        if not is_creator:
            return json_error("Only the analysis creator can reopen a rejected analysis.", status=403)

        analysis.status = GelAnalysis.Status.IN_PROGRESS
        analysis.rejection_reason = ""
        analysis.approved_by = None
        analysis.approved_at = None
        analysis._change_reason = f"Reopened by {user.get_full_name() or user.username}"
        analysis.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at", "updated_at"])

    logger.info(
        f"Analysis status transition: {action}",
        user=user.username,
        analysis_id=str(pk),
        new_status=analysis.status,
    )

    return JsonResponse(
        {
            "success": True,
            "status": analysis.status,
            "status_display": analysis.get_status_display(),
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
        log.error(f"Crop failed: {e}")
        return json_error(f"Crop failed: {e}", status=500)

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

    from gel_analyzer.services.band_detection.calibration import (
        DetectionCalibrator,
        TeachingRegion,
    )
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
        log.error(f"Failed to load image: {e}")
        return json_error(f"Failed to load image: {e}", status=500)

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
        log.error(f"Calibration failed: {e}")
        return json_error(f"Calibration failed: {e}", status=500)

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
        params = CV2DetectionParams.from_dict(params_dict)
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

    except ValueError as e:
        logger.warning(f"Invalid CV2 detection params: {e}")
        return json_error(f"Invalid parameters: {e}")
    except Exception as e:
        logger.exception(f"CV2 band detection failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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
        params = CV2DetectionParams.from_dict(params_dict)
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

    except ValueError as e:
        logger.warning(f"Invalid CV2 detection params: {e}")
        return json_error(f"Invalid parameters: {e}")
    except Exception as e:
        logger.exception(f"CV2 band detection save failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


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


@login_required
@require_http_methods(["POST"])
def api_detect_bands_hybrid_lane(request, pk):
    """POST: Hybrid detection in a single lane (preview mode, no DB write)."""
    from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
    from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
    from gel_analyzer.services.file_handler import GelFileHandler

    lane = get_object_or_404(Lane.objects.select_related("analysis__gel_image"), pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    params_dict = data.get("params", data) if data else {}

    try:
        params = HybridDetectionParams.from_dict(params_dict)
        image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)

        b = lane.bbox
        x, y, w, h = b["x"], b["y"], b["width"], b["height"]
        lane_crop = image[y : y + h, x : x + w]

        detector = HybridDetector(params)
        bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h))

        response = {
            "success": True,
            "lane_id": lane.pk,
            "lane_number": lane.lane_number,
            "bands": [band.to_dict() for band in bands],
            "band_count": len(bands),
            "summary": detector.last_summary,
            "params_used": params.to_dict(),
        }

        logger.info(
            f"Hybrid detection preview for lane {lane.lane_number}",
            user=request.user.username,
            lane_id=pk,
            band_count=len(bands),
        )
        return JsonResponse(response)

    except ValueError as e:
        logger.warning(f"Invalid hybrid detection params: {e}")
        return json_error(f"Invalid parameters: {e}")
    except Exception as e:
        logger.exception(f"Hybrid band detection failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_hybrid_lane_save(request, pk):
    """POST: Hybrid detection in a single lane — save to DB."""
    from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
    from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
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

    try:
        params = HybridDetectionParams.from_dict(params_dict)
        image = GelFileHandler.load_image_as_array(analysis.gel_image)

        b = lane.bbox
        x, y, w, h = b["x"], b["y"], b["width"], b["height"]
        lane_crop = image[y : y + h, x : x + w]

        detector = HybridDetector(params)
        bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h))

        if delete_existing:
            # Replace ALL auto-detected bands (hybrid, CV2/d1d2, profile,
            # CV2 vision, YOLO, SAM) but preserve MANUAL annotations (user-
            # created bands via Ctrl+click or drag-to-draw). The user ran a
            # new detection method — they want the previous auto results
            # replaced, not stacked.
            auto_sources = [
                Band.DetectionSource.HYBRID,
                Band.DetectionSource.AUTO,
                Band.DetectionSource.CV2_VISION,
                Band.DetectionSource.PROFILE,
                Band.DetectionSource.YOLO,
                Band.DetectionSource.SAM,
            ]
            Band.objects.filter(
                lane=lane,
                detection_source__in=auto_sources,
            ).delete()

        band_type = "MW_REFERENCE" if lane.lane_type == Lane.LaneType.LADDER else "OTHER"

        for i, detected in enumerate(bands, 1):
            band_metadata = {
                "hybrid_phase": getattr(detected, "_hybrid_phase", "primary"),
            }
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
                detection_source=Band.DetectionSource.HYBRID,
                band_type=band_type,
                intensity_raw=detected.intensity_raw,
                intensity_peak=detected.intensity_peak,
                area_pixels=detected.area_pixels,
                metadata=band_metadata,
                created_by=request.user,
            )

        analysis.update_counts()

        saved_bands = lane.bands.filter(
            detection_source=Band.DetectionSource.HYBRID,
        ).order_by("position_y")

        logger.info(
            f"Saved {len(bands)} hybrid bands for lane {lane.lane_number}",
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
                "summary": detector.last_summary,
            }
        )

    except ValueError as e:
        logger.warning(f"Invalid hybrid detection params: {e}")
        return json_error(f"Invalid parameters: {e}")
    except Exception as e:
        logger.exception(f"Hybrid band detection save failed for lane {pk}: {e}")
        return json_error("An unexpected error occurred. Please try again.", 500)


@login_required
@require_http_methods(["POST"])
def api_detect_bands_hybrid_async(request, pk):
    """POST: Start async hybrid band detection for an analysis."""
    from gel_analyzer.tasks import detect_bands_hybrid_bulk_task

    analysis = get_object_or_404(GelAnalysis, pk=pk)

    data = parse_json_body(request)
    if data is None:
        return json_error("Invalid JSON in request body")
    params_dict = data.get("params", data) if data else {}
    raw_lane_ids = data.get("lane_ids") if data else None
    save_results = data.get("save_results", False) if data else False

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
        task = detect_bands_hybrid_bulk_task.delay(
            analysis_id=str(pk),
            lane_ids=lane_ids,
            params_dict=params_dict,
            user_id=request.user.pk if save_results else None,
            save_results=save_results,
        )
    except Exception:
        logger.exception(f"Failed to start async hybrid detection for analysis {pk}")
        return json_error(
            "Could not start background task. The task queue may be unavailable.",
            status=503,
        )

    logger.info(
        f"Started async hybrid band detection task {task.id}",
        user=request.user.username,
        analysis_id=str(pk),
        save_results=save_results,
    )

    return JsonResponse(
        {
            "success": True,
            "task_id": task.id,
            "analysis_id": str(pk),
            "message": "Hybrid band detection task started",
        }
    )


# ---------------------------------------------------------------------------
# Cross-Lane Consensus API (POST run / DELETE undo)
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["POST", "DELETE"])
def cross_lane_consensus_view(request, analysis_id):
    """POST: run consensus (dry_run or apply). DELETE: undo a run by run_id."""
    from gel_analyzer.services.band_detection.cross_lane_consensus import (
        CrossLaneConsensus,
        CrossLaneConsensusParams,
        serialize_consensus_result,
    )

    try:
        analysis = GelAnalysis.objects.get(id=analysis_id)
    except GelAnalysis.DoesNotExist:
        return json_error("analysis_not_found", status=404)

    if request.method == "DELETE":
        run_id = request.GET.get("run_id")
        if not run_id:
            return json_error("missing_run_id", status=400)
        qs = Band.objects.filter(
            lane__analysis=analysis,
            metadata__consensus_run_id=run_id,
        )
        n = qs.count()
        if n == 0:
            return JsonResponse({"error": "run_not_found", "deleted_count": 0}, status=404)
        with transaction.atomic():
            qs.delete()
        return JsonResponse({"deleted_count": n})

    # POST
    body = parse_json_body(request) or {}
    dry_run = bool(body.get("dry_run", True))
    params_data = body.get("params") or {}
    try:
        params = CrossLaneConsensusParams.from_dict(params_data)
        params.validate()
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": "invalid_params", "details": str(exc)}, status=400)

    # Count lanes with bands
    lanes_with_bands = analysis.lanes.filter(bands__isnull=False).distinct().count()
    if lanes_with_bands < 3:
        return JsonResponse(
            {
                "error": "insufficient_lanes",
                "message": "Cross-lane consensus requires at least 3 lanes with bands. "
                "Run detection on more lanes first.",
            },
            status=400,
        )

    try:
        svc = CrossLaneConsensus(params)
        result = svc.run(analysis, dry_run=dry_run)
    except Exception as exc:
        logger.exception(f"[CLC] Internal error: {exc}")
        return json_error("internal_error", status=500)

    added_band_ids = None
    if not dry_run:
        added_band_ids = list(
            Band.objects.filter(
                metadata__consensus_run_id=str(result.run_id),
            ).values_list("id", flat=True)
        )

    return JsonResponse(
        {
            "result": serialize_consensus_result(result),
            "added_band_ids": added_band_ids,
        }
    )
