"""Ladder Template Studio — dedicated cross-gel training UX.

Page view + 3 AJAX endpoints:
- GET  /admin/templates/<pk>/studio/                — the studio page
- GET  /api/admin/templates/<pk>/studio/lanes/      — available LADDER lanes
- POST /api/admin/templates/<pk>/studio/auto-assign/ — top-N auto assignment
- POST /api/admin/templates/<pk>/studio/save/       — persist calibrations + train

Staff-only. Non-destructive until Save.
"""

from __future__ import annotations

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST

from gel_analyzer.models import LadderTemplate
from gel_analyzer.services.studio import StudioService
from gel_analyzer.services.template_learning import TemplateLearningService
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _studio_service() -> StudioService:
    return StudioService()


@staff_member_required
def template_studio_view(request, pk):
    """Render the Studio page for a single ladder template."""
    template = get_object_or_404(LadderTemplate, pk=pk)
    learning = TemplateLearningService()
    summary = learning.get_training_summary(template)
    band_definitions = list(
        template.bands.order_by("band_order").values(
            "band_order",
            "mw_kda",
            "expected_rf",
            "expected_rf_tolerance",
            "is_reference_band",
            "color",
        )
    )
    context = {
        "template": template,
        "training_summary": summary,
        "band_definitions_json": json.dumps(band_definitions),
        "title": f"Studio: {template.name}",
    }
    return render(request, "gel_analyzer/admin/template_studio.html", context)


@staff_member_required
@require_http_methods(["GET"])
def api_studio_lanes_available(request, pk):
    """List LADDER lanes across analyses, optionally filtered."""
    template = get_object_or_404(LadderTemplate, pk=pk)
    analysis_id = request.GET.get("analysis_id") or None
    only_with_bands = request.GET.get("only_with_bands", "1") not in ("0", "false", "False")
    exclude_already = request.GET.get("exclude_calibrated", "0") in ("1", "true", "True")
    try:
        limit = max(1, min(int(request.GET.get("limit", 100)), 500))
        offset = max(0, int(request.GET.get("offset", 0)))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_params"}, status=400)

    payload = _studio_service().list_available_lanes(
        template,
        analysis_id=analysis_id,
        only_with_bands=only_with_bands,
        exclude_already_calibrated_for_this_template=exclude_already,
        limit=limit,
        offset=offset,
    )
    return JsonResponse(payload)


@staff_member_required
@require_POST
def api_studio_auto_assign(request, pk):
    """Run auto-assignment on the supplied lanes.

    Body accepts optional ``override_bands``: a ``{lane_id: [candidate, ...]}``
    mapping. When present, those candidates replace the DB-stored bands for
    that lane (ephemeral; not persisted). Used by the re-detect flow.
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)
    lane_ids = body.get("lane_ids") or []
    if not isinstance(lane_ids, list) or not lane_ids:
        return JsonResponse({"error": "lane_ids_required"}, status=400)
    if len(lane_ids) > 20:
        return JsonResponse({"error": "too_many_lanes", "max": 20}, status=400)
    override_bands = body.get("override_bands") or {}
    if not isinstance(override_bands, dict):
        return JsonResponse({"error": "override_bands_must_be_dict"}, status=400)
    payload = _studio_service().auto_assign(
        template,
        [str(x) for x in lane_ids],
        override_bands={str(k): v for k, v in override_bands.items() if isinstance(v, list)},
    )
    return JsonResponse(payload)


@staff_member_required
@require_POST
def api_studio_redetect(request, pk):
    """Profile + noise-subtraction re-detection for selected lanes.

    Returns fresh candidate peaks (not persisted). The client feeds these
    back to ``auto-assign`` via ``override_bands`` to re-run matching on
    the richer candidate set.
    """
    _ = get_object_or_404(LadderTemplate, pk=pk)  # auth + 404 gate
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)
    lane_ids = body.get("lane_ids") or []
    if not isinstance(lane_ids, list) or not lane_ids:
        return JsonResponse({"error": "lane_ids_required"}, status=400)
    if len(lane_ids) > 20:
        return JsonResponse({"error": "too_many_lanes", "max": 20}, status=400)
    try:
        payload = _studio_service().redetect_with_profile([str(x) for x in lane_ids])
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Studio redetect failed: {exc}", exc_info=True)
        return JsonResponse({"error": "internal_error", "detail": str(exc)}, status=500)
    return JsonResponse(payload)


@staff_member_required
@require_POST
def api_studio_save(request, pk):
    """Persist calibrations + trigger template learning. Atomic."""
    template = get_object_or_404(LadderTemplate, pk=pk)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)
    lanes_payload = body.get("lanes") or []
    if not isinstance(lanes_payload, list) or not lanes_payload:
        return JsonResponse({"error": "lanes_required"}, status=400)
    try:
        result = _studio_service().save_training(template, lanes_payload, user=request.user)
    except ValueError as exc:
        return JsonResponse({"error": "invalid_payload", "detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Studio save failed for template {template.code}: {exc}",
            user=request.user.username,
            template_id=str(template.pk),
            exc_info=True,
        )
        return JsonResponse({"error": "internal_error", "detail": str(exc)}, status=500)
    return JsonResponse({"ok": True, **result})
