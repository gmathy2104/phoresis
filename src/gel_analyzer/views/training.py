"""
Training views for MW ladder template calibration.

These views allow administrators to train Rf patterns from annotated gels,
enabling template-guided band detection that filters ghost bands.

Access: Superuser and staff members only.
"""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from gel_analyzer.models import LadderCalibration, LadderTemplate
from gel_analyzer.services import TemplateLearningService
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


@staff_member_required
def template_training_list_view(request):
    """
    List all ladder templates with their training status.

    Shows which templates have learned Rf patterns and need more training data.
    """
    service = TemplateLearningService()

    templates = LadderTemplate.objects.filter(is_active=True).order_by("manufacturer", "name")

    template_data = []
    for template in templates:
        summary = service.get_training_summary(template)
        template_data.append(
            {
                "template": template,
                "summary": summary,
            }
        )

    context = {
        "template_data": template_data,
        "title": "MW Template Training",
    }

    return render(request, "gel_analyzer/admin/template_training_list.html", context)


@staff_member_required
def template_calibration_view(request, pk):
    """
    Training view to calibrate Rf patterns for a specific template.

    Shows existing calibrations and computed Rf statistics.
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    service = TemplateLearningService()

    # Get calibrations for this template
    calibrations = (
        LadderCalibration.objects.filter(template=template)
        .select_related("ladder_lane", "analysis", "analysis__gel_image")
        .order_by("-created_at")
    )

    # Compute current Rf statistics
    band_rf_data = service.compute_rf_statistics(template, calibrations)

    # Get training summary
    training_summary = service.get_training_summary(template)

    context = {
        "template": template,
        "calibrations": calibrations,
        "band_rf_data": band_rf_data,
        "training_summary": training_summary,
        "calibration_count": calibrations.count(),
        "title": f"Train Template: {template.name}",
    }

    return render(request, "gel_analyzer/admin/template_calibration.html", context)


@staff_member_required
@require_POST
def template_save_rf_patterns_view(request, pk):
    """
    Save computed Rf patterns to template bands.

    POST data:
    - calibration_ids: list of calibration UUIDs to use (optional, all if empty)
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    service = TemplateLearningService()

    # Get selected calibration IDs
    calibration_ids = request.POST.getlist("calibration_ids")

    # Learn and save patterns
    try:
        result = service.learn_rf_patterns(
            template=template,
            calibration_ids=calibration_ids if calibration_ids else None,
        )

        logger.info(
            f"Saved Rf patterns for template {template.code}",
            user=request.user.username,
            template_id=str(template.pk),
            updated_bands=result["updated_bands"],
        )

        messages.success(
            request,
            f"Saved Rf patterns for {result['updated_bands']} bands from {result['calibration_count']} calibrations.",
        )

    except Exception as e:
        logger.error(
            f"Error saving Rf patterns: {e}",
            user=request.user.username,
            template_id=str(template.pk),
            exc_info=True,
        )
        messages.error(request, f"Error saving patterns: {str(e)}")

    return redirect("gel_analyzer:admin_template_calibration", pk=pk)


@staff_member_required
@require_POST
def template_clear_rf_patterns_view(request, pk):
    """
    Clear all learned Rf patterns from a template.
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    service = TemplateLearningService()

    try:
        cleared = service.clear_rf_patterns(template)

        logger.info(
            f"Cleared Rf patterns for template {template.code}",
            user=request.user.username,
            template_id=str(template.pk),
            cleared_bands=cleared,
        )

        messages.success(request, f"Cleared Rf patterns from {cleared} bands.")

    except Exception as e:
        logger.error(
            f"Error clearing Rf patterns: {e}",
            user=request.user.username,
            template_id=str(template.pk),
            exc_info=True,
        )
        messages.error(request, f"Error clearing patterns: {str(e)}")

    return redirect("gel_analyzer:admin_template_calibration", pk=pk)


@staff_member_required
@require_http_methods(["GET"])
def api_template_training_status(request, pk):
    """
    API endpoint to get training status for a template.

    GET: Returns training summary and Rf statistics.
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    service = TemplateLearningService()

    # Get summary and statistics
    summary = service.get_training_summary(template)
    band_data = service.compute_rf_statistics(template)

    return JsonResponse(
        {
            "template_id": str(template.pk),
            "template_name": template.name,
            "summary": summary,
            "bands": band_data,
        }
    )


@staff_member_required
@require_POST
def api_template_train_now(request, pk):
    """Trigger Rf pattern learning for a template from its existing calibrations.

    AJAX endpoint used by the "Train now" shortcut on the training list page.
    No body required — aggregates all existing calibrations for the template.
    Returns the refreshed training summary for UI update.
    """
    template = get_object_or_404(LadderTemplate, pk=pk)
    service = TemplateLearningService()
    try:
        result = service.learn_rf_patterns(template=template)
        summary = service.get_training_summary(template)
        logger.info(
            f"Train-now: template {template.code}",
            user=request.user.username,
            template_id=str(template.pk),
            updated_bands=result["updated_bands"],
            calibration_count=result["calibration_count"],
        )
        return JsonResponse(
            {
                "ok": True,
                "result": result,
                "summary": summary,
            }
        )
    except Exception as exc:
        logger.error(
            f"Train-now failed for template {template.code}: {exc}",
            user=request.user.username,
            template_id=str(template.pk),
            exc_info=True,
        )
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
