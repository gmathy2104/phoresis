"""Analysis HTML views.

Provides:
- analysis_list_view: List the analyses: pill filters (status, assay, creator), cards or table, compare
- analysis_create_view: Create new analysis for an image
- analysis_detail_view: The analysis page, read for what its gel measures; lanes editable in the spreadsheet
- analysis_annotate_view: Interactive annotation editor

Resynced with `$DSHUB/gel_analyzer/views/analyses.py`; the hub's sample links and
projects do not exist in Phoresis: a lane carries a free-text `sample_name`.
"""

from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from gel_analyzer.forms.analysis_forms import GelAnalysisCreateForm, lane_to_dict
from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane
from gel_analyzer.services.analysis_detail import READOUT_LABELS, page_readout, page_summary
from gel_analyzer.services.analysis_status import user_is_gel_qa
from gel_analyzer.services.list_filters import (
    NONE_VALUE,
    choice_values,
    facet,
    facet_chips,
    ids_q,
    int_values,
    remove_value_url,
    selected_values,
)
from phoresis_core.logging_config import get_logger
from phoresis_core.safe_json import script_json

logger = get_logger(__name__)


# =============================================================================
# Helper Functions for Analysis Context
# =============================================================================


# key -> (order_by field, label of the Sort select)
_ANALYSIS_SORTS = {
    "-created_at": ("-created_at", "Newest first"),
    "created_at": ("created_at", "Oldest first"),
    "name": ("name", "Name A-Z"),
    "-name": ("-name", "Name Z-A"),
    "-lanes": ("-total_lanes", "Most lanes"),
}


def _user_label(first_name, last_name, username):
    """Full name, else the username -- from a ``.values()`` row."""
    return f"{first_name} {last_name}".strip() or username


# The pills' counts are over ALL analyses, never cross-filtered by the other pills:
# a count that moves when another filter changes confuses more than it helps (the
# image list follows the same rule).


def _status_facet(statuses):
    """
    Status pill: the five statuses in their workflow order, each with its count (0 included).

    Returns ``(facet, total)``: the counts of every status add up to the header's total.
    """
    counts = {
        row["status"]: row["n"] for row in GelAnalysis.objects.order_by().values("status").annotate(n=Count("pk"))
    }
    options = [(value, label, counts.get(value, 0)) for value, label in GelAnalysis.Status.choices]
    return facet("status", "Status", options, statuses), sum(counts.values())


def _assay_facet(assay_ids, assay_none):
    """Assay pill: the assays of the analysed images, in their display order, then "No assay"."""
    rows = (
        GelAnalysis.objects.order_by()
        .values("gel_image__assay", "gel_image__assay__name", "gel_image__assay__display_order")
        .annotate(n=Count("pk"))
    )
    assays, without_assay = [], 0
    for row in rows:
        if row["gel_image__assay"] is None:
            without_assay = row["n"]
        else:
            assays.append(row)
    assays.sort(key=lambda row: (row["gel_image__assay__display_order"], row["gel_image__assay__name"].lower()))
    options = [(row["gel_image__assay"], row["gel_image__assay__name"], row["n"]) for row in assays]
    if without_assay or assay_none:
        options.append((NONE_VALUE, "No assay", without_assay))
    return facet("assay", "Assay", options, selected_values(assay_ids, assay_none))


def _creator_facet(creator_ids):
    """Created-by pill: the users who created analyses, by full name (else username)."""
    rows = (
        GelAnalysis.objects.filter(created_by__isnull=False)
        .order_by()
        .values("created_by", "created_by__first_name", "created_by__last_name", "created_by__username")
        .annotate(n=Count("pk"))
    )
    options = [
        (
            row["created_by"],
            _user_label(row["created_by__first_name"], row["created_by__last_name"], row["created_by__username"]),
            row["n"],
        )
        for row in rows
    ]
    options.sort(key=lambda option: option[1].lower())
    return facet("created_by", "Created by", options, selected_values(creator_ids))


@login_required
def analysis_list_view(request: HttpRequest) -> HttpResponse:
    """
    List the analyses: a pill filter bar, cards or a table, paginated, and lane comparison.

    The bar is one GET form, so every filter lives in the URL:

    - ``q``: search in the analysis name and the image's file name
    - ``status``: repeated ``GelAnalysis.Status`` values (a single ``?status=COMPLETED``
      from a link elsewhere keeps working)
    - ``assay``: the image's, repeated ids plus ``none``
    - ``created_by``: repeated user ids
    - ``sort`` (``_ANALYSIS_SORTS``), ``view`` (``cards`` / ``table``), ``page``

    Each analysis carries its lane ids (``lane_ids_json``: the "Compare (N)" button
    sends the lanes of the ticked analyses to the sample comparison).
    """
    params = request.GET
    search_query = params.get("q", "").strip()
    statuses = choice_values(params, "status", GelAnalysis.Status.values)
    assay_ids, assay_none = int_values(params, "assay")
    creator_ids, _ = int_values(params, "created_by")
    view_mode = "table" if params.get("view") == "table" else "cards"
    sort_by = params.get("sort", "-created_at")
    if sort_by not in _ANALYSIS_SORTS:
        sort_by = "-created_at"

    analyses = (
        GelAnalysis.objects.select_related("gel_image__assay", "created_by")
        # The lane ids only: a lane row carries its polygon (JSON), never read here.
        .prefetch_related(Prefetch("lanes", queryset=Lane.objects.order_by("lane_number").only("pk", "analysis")))
        # -pk breaks the ties ("Most lanes" has many) so a page never repeats an analysis.
        .order_by(_ANALYSIS_SORTS[sort_by][0], "-pk")
        .filter(
            ids_q("gel_image__assay", assay_ids, assay_none),
            ids_q("created_by", creator_ids),
        )
    )
    if statuses:
        analyses = analyses.filter(status__in=statuses)
    if search_query:
        analyses = analyses.filter(
            Q(name__icontains=search_query) | Q(gel_image__original_filename__icontains=search_query)
        )

    paginator = Paginator(analyses, 24)
    page_obj = paginator.get_page(params.get("page", 1))
    analyses_list = list(page_obj.object_list)
    for analysis in analyses_list:
        analysis.lane_ids_json = json.dumps([lane.pk for lane in analysis.lanes.all()])

    status_facet, total_count = _status_facet(statuses)
    facets = [
        status_facet,
        _assay_facet(assay_ids, assay_none),
        _creator_facet(creator_ids),
    ]
    chips = facet_chips(params, facets)
    if search_query:
        chips.append({"label": f'Search: "{search_query}"', "url": remove_value_url(params, "q", params.get("q"))})

    context = {
        "page_title": "Analyses",
        "page_obj": page_obj,
        "analyses": analyses_list,
        # The single status select of the Phoresis page: the first ticked value.
        "status_filter": statuses[0] if statuses else "",
        "status_choices": GelAnalysis.Status.choices,
        "total_count": total_count,
        "facets": facets,
        "chips": chips,
        "search_query": search_query,
        "view_mode": view_mode,
        "sort_by": sort_by,
        "sort_choices": [(key, label) for key, (_, label) in _ANALYSIS_SORTS.items()],
    }

    return render(request, "gel_analyzer/analyses/list.html", context)


@login_required
def analysis_create_view(request: HttpRequest, image_pk) -> HttpResponse:
    gel_image = get_object_or_404(GelImage, pk=image_pk)

    if request.method == "POST":
        form = GelAnalysisCreateForm(request.POST, gel_image=gel_image)
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
        # Phoresis names a new analysis after its file; the form's own suggestion is the fallback.
        form = GelAnalysisCreateForm(gel_image=gel_image, initial={"name": gel_image.original_filename})

    context = {
        "page_title": "New Analysis",
        "form": form,
        "gel_image": gel_image,
    }

    return render(request, "gel_analyzer/analyses/create.html", context)


@login_required
def analysis_detail_view(request: HttpRequest, pk) -> HttpResponse:
    """
    The analysis page, read for what its gel measures (``services/analysis_detail.py``).

    Header (assay, status and next step), the checks the gel's readout needs, metric cards, the
    annotated gel, and the lanes as cards or as the lane spreadsheet -- where samples are named
    and the lane fields edited while the analysis is editable.
    """
    lane_bands = Prefetch("bands", queryset=Band.objects.select_related("densitometry"))
    lanes_qs = (
        Lane.objects.select_related("ladder_template", "densitometry_summary")
        .prefetch_related(lane_bands)
        .order_by("lane_number", "pk")
    )
    # The lanes are prefetched WHOLE on the analysis: lane_readouts then reads them, the reference
    # lane included, with no query of its own (its docstring).
    analysis = get_object_or_404(
        GelAnalysis.objects.select_related(
            "gel_image__assay",
            "created_by",
            "approved_by",
            "multi_ladder_config__template",
            "readout_reference_lane",
        ).prefetch_related(
            "ladder_calibrations__ladder_lane",
            "ladder_calibrations__template",
            Prefetch("lanes", queryset=lanes_qs),
        ),
        pk=pk,
    )
    lanes_list = list(analysis.lanes.all())
    gel_image = analysis.gel_image

    # The readout, its lane values, checks and cards: one composition shared with the densitometry page.
    summary = page_summary(analysis, lanes_list)
    columns, rows, checks = summary["columns"], summary["rows"], summary["checks"]
    read_rows = [row for row in rows if row["is_read"]]

    # The lane spreadsheet: lane_to_dict (its editable fields) + the row's cells. The cards read
    # the same cells, in column order (a template cannot index a dict by a variable key).
    no_cell = {"text": "", "reason": None, "tone": None}
    lanes_payload = []
    densitometry_lanes = []
    for lane, row in zip(lanes_list, rows, strict=False):
        row["lane"] = lane
        row["cell_list"] = [
            {**row["cells"].get(column["key"], no_cell), "label": column["label"], "title": column["title"]}
            for column in columns
        ]
        data = lane_to_dict(lane)
        data["cells"] = row["cells"]
        data["is_reference"] = row["is_reference"]
        # Read-only stats the Phoresis lane spreadsheet (lane-spreadsheet.js) shows without re-fetching.
        purity = row["values"].get("purity")
        data["_band_count"] = row["band_count"]
        data["poi_kda"] = float(row["poi_kda"]) if row["poi_kda"] is not None else None
        data["purity"] = purity
        lanes_payload.append(data)
        if lane.lane_type == Lane.LaneType.SAMPLE and row["analysed"]:
            densitometry_lanes.append(
                {
                    "lane_number": lane.lane_number,
                    "sample_name": lane.sample_name,
                    "poi_percentage": purity,
                    "band_count": row["band_count"],
                }
            )

    # What the Phoresis detail template reads today (analyses/detail.html): the purity average of
    # its overview card and the data-quality list, both derived from the summary above.
    purities = [entry["poi_percentage"] for entry in densitometry_lanes if entry["poi_percentage"] is not None]
    densitometry_info = {
        "has_results": bool(densitometry_lanes),
        "lanes": densitometry_lanes,
        "average_purity": round(sum(purities) / len(purities), 1) if purities else None,
    }
    warnings = [{"type": check["kind"], "message": check["title"]} for check in checks if check["level"] == "warn"]

    context = {
        "page_title": analysis.name,
        "analysis": analysis,
        "gel_image": gel_image,
        "lanes": lanes_list,
        "lanes_json": script_json(lanes_payload),
        "columns": columns,
        "columns_json": script_json(columns),
        "rows": rows,
        "read_rows": read_rows,
        "readout": summary["readout"],
        "readout_label": summary["readout_label"],
        "checks": checks,
        "warn_count": sum(1 for check in checks if check["level"] == "warn"),
        "next_step": summary["next_step"],
        "headline": summary["headline"],
        "sample_count": summary["sample_count"],
        "control_count": summary["control_count"],
        "analysed_count": summary["analysed_count"],
        "read_count": summary["read_count"],
        "can_edit_samples": analysis.is_editable,
        # The approve/reject buttons follow the rule that grants the action (services/analysis_status.py)
        "user_is_qa": user_is_gel_qa(request.user),
        "image_width": gel_image.width,
        "image_height": gel_image.height,
        "calibration_info": summary["calibration_info"],
        "quant_calibration_info": summary["quant_calibration_info"],
        # Keys of the current Phoresis template, kept until it reads the summary's own.
        "densitometry_info": densitometry_info,
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
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image__assay"), pk=pk)

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
        # What the workbench header's assay chip says the gel is read for (workbench/_identity.html). The
        # page summary itself comes with /data/ (api_analysis_data), which the editor loads at boot.
        "readout_label": READOUT_LABELS[page_readout(analysis.gel_image)],
    }

    # Use standalone template (Bootstrap-free) for better control
    return render(request, "gel_analyzer/analyses/annotate_standalone.html", context)
