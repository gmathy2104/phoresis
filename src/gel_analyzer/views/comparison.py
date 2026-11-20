"""
Sample Comparison views for gel_analyzer.

Provides views for comparing gel densitometry results across multiple lanes.
Supports two entry modes:
- Lane mode: ?lanes=123,456,789 (Lane IDs directly from gel_analyzer)
- Saved comparison: ?comparison=<uuid>

ProcessSample integration was removed in Phoresis (Phase 2): per-lane sample
metadata now lives on `Lane.sample_metadata` (JSON) and `Lane.sample_name`.
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.shortcuts import render

from gel_analyzer.access import saved_comparisons_readable_by, user_can_read_saved_comparison
from gel_analyzer.models import GelAnalysis, Lane, SavedComparison, SavedComparisonLane
from gel_analyzer.services.analysis_detail import PURITY_FAIR, PURITY_GOOD, assay_label
from gel_analyzer.services.comparison_items import enrich, kind_key, lane_item
from gel_analyzer.services.list_filters import (
    NONE_VALUE,
    facet,
    facet_chips,
    ids_q,
    int_values,
    remove_value_url,
    selected_values,
)
from phoresis_core.logging_config import get_logger
from phoresis_core.safe_json import script_json
from phoresis_core.safe_redirect import safe_back_path

logger = get_logger(__name__)


# The lane item now lives in services/comparison_items.py (one builder for the page, the wizard, the
# resolve endpoint and the PD gel slots); the old name stays importable.
_serialize_lane_data = lane_item


def _visible_comparisons(user, mode):
    """The saved comparisons the list shows: the user's own ("mine"), or every one they may read ("all":
    theirs and the public ones) -- ``access.saved_comparisons_readable_by``, the one owner-or-public rule
    of the API, the report route and the compare page."""
    if mode == "mine":
        return SavedComparison.objects.filter(created_by_id=user.pk)
    return saved_comparisons_readable_by(user, SavedComparison.objects.all())


def _comparison_assay_facet(visible, assay_ids, assay_none):
    """Assay pill: the assays of the visible comparisons' lanes, each counting the comparisons holding one."""
    rows = (
        SavedComparisonLane.objects.filter(saved_comparison__in=visible)
        .order_by()
        .values(
            "lane__analysis__gel_image__assay",
            "lane__analysis__gel_image__assay__name",
            "lane__analysis__gel_image__assay__display_order",
        )
        .annotate(n=Count("saved_comparison", distinct=True))
    )
    assays, without_assay = [], 0
    for row in rows:
        if row["lane__analysis__gel_image__assay"] is None:
            without_assay = row["n"]
        else:
            assays.append(row)
    assays.sort(
        key=lambda row: (
            row["lane__analysis__gel_image__assay__display_order"],
            row["lane__analysis__gel_image__assay__name"].lower(),
        )
    )
    options = [
        (row["lane__analysis__gel_image__assay"], row["lane__analysis__gel_image__assay__name"], row["n"])
        for row in assays
    ]
    if without_assay or assay_none:
        options.append((NONE_VALUE, "No assay", without_assay))
    return facet("assay", "Assay", options, selected_values(assay_ids, assay_none))


def _comparison_card(comparison, user):
    """What a card of the list says of a saved comparison: its assays (the kinds the page shows one at a
    time, each with its lane count), its gels, its calibrated lanes, who and when."""
    lanes = [link.lane for link in comparison.savedcomparisonlane_set.all()]
    kinds = {}
    for lane in lanes:
        key = kind_key(lane.analysis.gel_image)
        kinds[key] = kinds.get(key, 0) + 1
    creator = comparison.created_by
    return {
        "comparison": comparison,
        "kinds": list(kinds.items()),
        "lane_count": len(lanes),
        "gel_count": len({lane.analysis_id for lane in lanes}),
        "calibrated_count": sum(1 for lane in lanes if lane.analysis.ladder_calibrations.all()),
        "creator": (creator.get_full_name() or creator.username) if creator else "Unknown",
        "is_owner": comparison.created_by_id == user.pk,
    }


@login_required
def comparison_list_view(request):
    """
    The saved comparisons and the analyses ready to compare, in the light gel-list look (slice 2d).

    One GET form (``partials/_filter_picker.html``, ``js/ga-filterbar.js``), so every filter lives in the URL:

    - ``filter``: ``mine`` (default) | ``all`` -- the user's comparisons, or theirs and the public ones
    - ``q``: search in the name and the description
    - ``assay``: repeated assay ids plus ``none`` -- the comparisons holding a lane of that assay
    - ``page``: 24 cards a page

    A card names the assays the comparison holds (the page compares one at a time). Delete stays the
    owner's, through the saved-comparison API. "Recent analyses with densitometry": the newest 20, with
    their assay, each a link comparing all its lanes.
    """
    params = request.GET
    mode = "all" if params.get("filter") == "all" else "mine"
    search_query = params.get("q", "").strip()
    assay_ids, assay_none = int_values(params, "assay")

    visible = _visible_comparisons(request.user, mode)
    comparisons = visible
    if search_query:
        comparisons = comparisons.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))
    if assay_ids or assay_none:
        comparisons = comparisons.filter(ids_q("lanes__analysis__gel_image__assay", assay_ids, assay_none)).distinct()
    comparisons = (
        comparisons.select_related("created_by")
        .prefetch_related(
            Prefetch(
                "savedcomparisonlane_set",
                queryset=SavedComparisonLane.objects.select_related("lane__analysis__gel_image__assay")
                .prefetch_related("lane__analysis__ladder_calibrations")
                .order_by("order"),
            )
        )
        .order_by("-updated_at", "-pk")
    )
    page_obj = Paginator(comparisons, 24).get_page(params.get("page", 1))
    cards = [_comparison_card(comparison, request.user) for comparison in page_obj.object_list]

    facets = [_comparison_assay_facet(visible, assay_ids, assay_none)]
    chips = facet_chips(params, facets)
    if search_query:
        chips.append({"label": f'Search: "{search_query}"', "url": remove_value_url(params, "q", params.get("q"))})

    # Recent analyses with completed densitometry. `annotate(lanes_count=...)` + `prefetch_related("lanes")`
    # let the template render the count and the "Compare lanes" link without 2 queries per row.
    recent_analyses = list(
        GelAnalysis.objects.filter(lanes__densitometry_summary__isnull=False)
        .select_related("gel_image__assay")
        .annotate(lanes_count=Count("lanes", distinct=True))
        .prefetch_related("lanes")
        .distinct()
        .order_by("-created_at")[:20]
    )
    for analysis in recent_analyses:
        # The image's assay as the gel pages name it (GelAnalysis has no gel type: the badge was empty).
        analysis.assay_label = assay_label(analysis.gel_image)

    context = {
        "cards": cards,
        "page_obj": page_obj,
        "total_count": visible.count(),
        "filter_mode": mode,
        "search_query": search_query,
        "facets": facets,
        "chips": chips,
        "recent_analyses": recent_analyses,
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
            # Access check: owner or public (access.py, the rule of the API and the report route)
            if not user_can_read_saved_comparison(request.user, saved_comparison):
                saved_comparison = None
        except (SavedComparison.DoesNotExist, ValueError, ValidationError):
            pass

    # Collect all items to compare
    items_data = []

    def _parse_id_param(values):
        """Accept ?x=1&x=2 and ?x=1,2 (comma form) — both per docstring above."""
        out = []
        for raw in values:
            for piece in str(raw).split(","):
                piece = piece.strip()
                if piece.isdigit():
                    out.append(piece)
        return out

    if saved_comparison:
        # Load lanes from saved comparison in order
        saved_lane_ids = list(
            saved_comparison.savedcomparisonlane_set.order_by("order").values_list("lane_id", flat=True)
        )
        # Feed into lane-mode processing below
        lane_ids_override = [str(lid) for lid in saved_lane_ids]

        saved_comparison_info = {
            "id": str(saved_comparison.pk),
            "name": saved_comparison.name,
            "description": saved_comparison.description,
            "is_public": saved_comparison.is_public,
            "view_settings": saved_comparison.view_settings or {},
            "lane_count": len(saved_lane_ids),
        }
    else:
        lane_ids_override = None

    # The page shows at most 20 lanes.
    SAMPLE_CAP = 20

    # The hub also resolves ?samples= (Process Development samples) into lanes here; a Phoresis
    # comparison is made of lanes only.
    lane_ids_input = lane_ids_override if lane_ids_override else _parse_id_param(request.GET.getlist("lanes", []))
    remaining_slots = SAMPLE_CAP
    lane_mode_ids = [int(x) for x in lane_ids_input[:remaining_slots] if str(x).isdigit()]
    if saved_comparison:
        # A saved comparison over the cap loads its first lanes: an Update would replace the saved lanes with
        # those and drop the rest without a word. The page refuses Update then (comparison-page-chrome.js),
        # on this flag -- decided here, once, not from the lanes the user adds or removes afterwards.
        saved_comparison_info["truncated"] = len(lane_ids_input) > len(lane_mode_ids)
        saved_comparison_json = script_json(saved_comparison_info)

    # === Bulk fetch for lane-mode lanes ===
    lanes_by_id = {}
    if lane_mode_ids:
        lanes_qs = (
            Lane.objects.filter(pk__in=lane_mode_ids)
            .select_related(
                "analysis__gel_image",
                "densitometry_summary",
            )
            .prefetch_related(
                "bands__densitometry",
                "analysis__ladder_calibrations__template",
            )
        )
        lanes_by_id = {lane_obj.pk: lane_obj for lane_obj in lanes_qs}

    for lane_id in lane_mode_ids:
        lane = lanes_by_id.get(lane_id)
        if lane is None:
            continue
        items_data.append(lane_item(lane))

    # What each lane is compared in and what it reads (the gel's own rules, services/analysis_detail.py).
    enrich(items_data)
    items_json = script_json(items_data)

    context = {
        "items_data": items_data,
        "items_json": items_json,
        # The purity thresholds of the gel pages (90 / 70), for the comparison's purity chart.
        "purity_thresholds_json": script_json({"good": PURITY_GOOD, "fair": PURITY_FAIR}),
        "can_add_more": True,
        # Saved comparison context
        "saved_comparison_id": str(saved_comparison.pk) if saved_comparison else "",
        "saved_comparison_name": saved_comparison.name if saved_comparison else "",
        "saved_comparison_json": saved_comparison_json,
        # Support ?back= parameter for return navigation. The value lands in an
        # href, so only an internal root-relative path is accepted; anything
        # else falls back to the template default and is never reflected.
        "back_url": safe_back_path(request) or "",
    }

    return render(request, "gel_analyzer/comparisons/compare.html", context)


@login_required
def viz_showcase_view(request):
    """Dev/demo: mounts the comparison component on an MDB5 page to prove
    inline reusability + inbound CSS containment + resolve endpoint + teardown."""
    return render(request, "gel_analyzer/viz/showcase.html", {"page_title": "Viz showcase · Gel Analyzer"})
