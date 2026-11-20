"""
API endpoints for Saved Comparisons.

Endpoints:
- GET/POST /api/comparisons/ — List/create saved comparisons
- GET/PUT/DELETE /api/comparisons/<uuid>/ — Retrieve/update/delete
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.access import (
    saved_comparisons_readable_by,
    user_can_read_saved_comparison,
    user_owns_saved_comparison,
)
from gel_analyzer.forms.comparison_forms import saved_comparison_to_dict
from gel_analyzer.models import Lane, SavedComparison, SavedComparisonLane
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _json_error(message, status=400):
    """Return a JSON error response."""
    return JsonResponse({"error": message}, status=status)


def _parse_json_body(request):
    """Parse JSON body from request. Returns None on decode failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None


@login_required
@require_http_methods(["GET", "POST"])
def api_saved_comparisons(request):
    """
    GET: List saved comparisons (user's own + public).
    POST: Create a new saved comparison.

    Query parameters (GET):
        filter: 'mine' (default), 'all', 'recent'
        search: text search on name
        page: page number (default 1)
        page_size: items per page (default 20)
    """
    if request.method == "GET":
        filter_mode = request.GET.get("filter", "mine")
        search = request.GET.get("search", "").strip()

        qs = SavedComparison.objects.select_related("created_by")

        if filter_mode == "mine":
            qs = qs.filter(created_by=request.user)
        else:
            # 'all' and 'recent' both show user's own + public
            qs = saved_comparisons_readable_by(request.user, qs)

        if search:
            qs = qs.filter(name__icontains=search)

        qs = qs.order_by("-updated_at")

        # Pagination
        try:
            page = max(1, int(request.GET.get("page", 1)))
            page_size = min(100, max(1, int(request.GET.get("page_size", 20))))
        except (ValueError, TypeError):
            page = 1
            page_size = 20

        total = qs.count()
        offset = (page - 1) * page_size
        comparisons = list(qs[offset : offset + page_size])

        return JsonResponse(
            {
                "results": [saved_comparison_to_dict(c) for c in comparisons],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )

    # POST: Create new comparison
    data = _parse_json_body(request)
    if data is None:
        return _json_error("Invalid JSON in request body")

    name = data.get("name", "").strip()
    if not name:
        return _json_error("Name is required")

    if len(name) > 255:
        return _json_error("Name must be 255 characters or fewer")

    lane_ids = data.get("lane_ids", [])
    if not lane_ids:
        return _json_error("At least one lane is required")

    # Validate all lane IDs exist
    valid_lanes = Lane.objects.filter(pk__in=lane_ids)
    valid_ids = set(valid_lanes.values_list("pk", flat=True))
    invalid_ids = [lid for lid in lane_ids if lid not in valid_ids]
    if invalid_ids:
        return _json_error(f"Invalid lane IDs: {invalid_ids}")

    comparison = SavedComparison.objects.create(
        name=name,
        description=data.get("description", ""),
        is_public=bool(data.get("is_public", False)),
        view_settings=data.get("view_settings", {}),
        created_by=request.user,
    )

    # Create through objects preserving order
    for order, lane_id in enumerate(lane_ids):
        SavedComparisonLane.objects.create(
            saved_comparison=comparison,
            lane_id=lane_id,
            order=order,
        )

    logger.info(
        f"Saved comparison created: {comparison.name} ({comparison.pk})",
        user=request.user.username,
        lane_count=len(lane_ids),
    )

    return JsonResponse(
        saved_comparison_to_dict(comparison, include_lanes=True),
        status=201,
    )


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_saved_comparison_detail(request, pk):
    """
    GET: Retrieve a saved comparison with lane details.
    PUT: Update name, description, settings, lanes, public flag.
    DELETE: Delete (owner only).
    """
    comparison = get_object_or_404(SavedComparison, pk=pk)

    # Access control: owner or public for read
    if not user_can_read_saved_comparison(request.user, comparison):
        return _json_error("Not found", 404)

    if request.method == "GET":
        return JsonResponse(saved_comparison_to_dict(comparison, include_lanes=True))

    # Write operations require ownership
    if not user_owns_saved_comparison(request.user, comparison):
        return _json_error("Permission denied", 403)

    if request.method == "PUT":
        data = _parse_json_body(request)
        if data is None:
            return _json_error("Invalid JSON in request body")

        if "name" in data:
            name = data["name"].strip()
            if not name:
                return _json_error("Name cannot be empty")
            if len(name) > 255:
                return _json_error("Name must be 255 characters or fewer")
            comparison.name = name

        if "description" in data:
            comparison.description = data["description"]

        if "is_public" in data:
            comparison.is_public = bool(data["is_public"])

        if "view_settings" in data:
            comparison.view_settings = data["view_settings"]

        comparison.save()

        # Update lanes if provided
        if "lane_ids" in data:
            lane_ids = data["lane_ids"]
            if not lane_ids:
                return _json_error("At least one lane is required")

            valid_lanes = Lane.objects.filter(pk__in=lane_ids)
            valid_ids = set(valid_lanes.values_list("pk", flat=True))
            invalid_ids = [lid for lid in lane_ids if lid not in valid_ids]
            if invalid_ids:
                return _json_error(f"Invalid lane IDs: {invalid_ids}")

            # Clear and recreate with new order
            SavedComparisonLane.objects.filter(saved_comparison=comparison).delete()

            for order, lane_id in enumerate(lane_ids):
                SavedComparisonLane.objects.create(
                    saved_comparison=comparison,
                    lane_id=lane_id,
                    order=order,
                )

        logger.info(
            f"Saved comparison updated: {comparison.name} ({comparison.pk})",
            user=request.user.username,
        )

        return JsonResponse(saved_comparison_to_dict(comparison, include_lanes=True))

    # DELETE
    comparison_name = comparison.name
    comparison.delete()

    logger.info(
        f"Saved comparison deleted: {comparison_name} ({pk})",
        user=request.user.username,
    )

    return JsonResponse({"deleted": True})
