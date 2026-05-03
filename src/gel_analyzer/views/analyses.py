"""Analysis HTML views (Phase 3 shells).

The heavy annotate/detail views land in Phase 4 — Phase 3 only ships list and
create. Logic ported from `$DSHUB/gel_analyzer/views/analyses.py` (list +
create only); ProcessSample / sample_analyses references already removed in
Phase 2's models — nothing further to strip here.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from gel_analyzer.forms.analysis_forms import GelAnalysisCreateForm
from gel_analyzer.models import GelAnalysis, GelImage
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


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
            messages.success(request, "Analysis created — open it to start annotating.")
            # Phase 4 redirects to detail; Phase 3 redirects to image detail.
            return redirect("gel_analyzer:image_detail", pk=gel_image.id)
    else:
        form = GelAnalysisCreateForm(initial={"name": gel_image.original_filename})

    return render(
        request,
        "gel_analyzer/analyses/create.html",
        {"gel_image": gel_image, "form": form},
    )
