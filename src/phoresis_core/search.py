"""Global search endpoint for the Ctrl+K command palette.

Returns a flat list of matching entities (analyses, comparisons, gel images)
the current user can see. Pages are handled client-side from the static
``nav_palette_items_json`` payload — this endpoint focuses on data.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from gel_analyzer.models import GelAnalysis, GelImage
from gel_analyzer.models.saved_comparison import SavedComparison

PER_TYPE_LIMIT = 6


@login_required
@require_GET
def api_global_search(request: HttpRequest) -> JsonResponse:
    """Return up to ``PER_TYPE_LIMIT`` matches per entity type for ``?q=…``."""
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    results: list[dict] = []
    user = request.user

    # ── Analyses ──────────────────────────────────────────────────────────
    analyses = (
        GelAnalysis.objects.select_related("gel_image")
        .filter(
            Q(name__icontains=q)
            | Q(notes__icontains=q)
            | Q(gel_image__original_filename__icontains=q)
        )
        .order_by("-updated_at")[:PER_TYPE_LIMIT]
    )
    for a in analyses:
        results.append(
            {
                "type": "analysis",
                "type_label": "Analysis",
                "icon": "layers",
                "name": a.name or f"Analysis · {a.gel_image.original_filename}",
                "subtitle": a.gel_image.original_filename if a.name else a.get_status_display(),
                "url": reverse("gel_analyzer:analysis_detail", kwargs={"pk": a.pk}),
            }
        )

    # ── Saved comparisons ─────────────────────────────────────────────────
    comparisons = (
        SavedComparison.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q),
            Q(created_by=user) | Q(is_public=True),
        )
        .order_by("-updated_at")[:PER_TYPE_LIMIT]
    )
    for c in comparisons:
        results.append(
            {
                "type": "comparison",
                "type_label": "Comparison",
                "icon": "grid-2x2",
                "name": c.name,
                "subtitle": c.description[:80] if c.description else f"{c.lanes.count()} lanes",
                "url": reverse("gel_analyzer:sample_comparison") + f"?comparison={c.pk}",
            }
        )

    # ── Gel images ────────────────────────────────────────────────────────
    images = (
        GelImage.objects.filter(original_filename__icontains=q)
        .order_by("-uploaded_at")[:PER_TYPE_LIMIT]
    )
    for img in images:
        results.append(
            {
                "type": "image",
                "type_label": "Gel image",
                "icon": "image",
                "name": img.original_filename,
                "subtitle": img.get_gel_type_display(),
                "url": reverse("gel_analyzer:image_detail", kwargs={"pk": img.pk}),
            }
        )

    return JsonResponse({"results": results, "query": q})
