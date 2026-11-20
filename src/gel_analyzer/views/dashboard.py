"""
The gel dashboard: pick gels and lanes, see them with the gel widgets.

One page (``/explore/``): on the left every analysed gel with its lanes, to tick; on the right the
whole gel of the lane in focus (``GelAnalyzer.Viz.SampleLaneGel``) and the comparison component
(``GelAnalyzer.Viz.Comparison``: lanes side by side on a common kDa axis, intensity profiles,
purity or western readout, band detail, band table) mounted with the ticked lanes.

The server only lists what can be picked. A lane's data comes from the endpoint the comparison
page already uses (``api_lane_comparison_data``: ``comparison_items.lane_item`` + ``enrich``), so
the dashboard draws exactly what the comparison page draws and computes nothing of its own.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from gel_analyzer.models import GelAnalysis, Lane, LaneDensitometrySummary
from gel_analyzer.services.analysis_detail import PURITY_FAIR, PURITY_GOOD, assay_label
from gel_analyzer.signals import image_measures_purity, published_purity
from phoresis_core.safe_json import script_json

# The picker lists the most recent analysed gels; older ones are reached from their own pages.
MAX_GELS = 200
# The comparison component draws at most this many lanes (views/comparison.py, SAMPLE_CAP).
MAX_LANES = 20


def _summary_of(lane):
    try:
        return lane.densitometry_summary
    except LaneDensitometrySummary.DoesNotExist:
        return None


def pickable_gels(limit: int = MAX_GELS) -> list[dict]:
    """The analysed gels and their lanes, newest first: what the dashboard's picker offers.

    A gel is listed once one of its lanes has a densitometry; a REJECTED analysis is left out (its
    values count nowhere). Every lane is listed, but only an analysed one can be ticked. The purity
    is the lane's published purity on a gel that measures one, else None -- never a 0 % for a lane
    whose POI was not typed (``signals.published_purity``).
    """
    analysed = LaneDensitometrySummary.objects.filter(lane__analysis=OuterRef("pk"))
    analyses = (
        GelAnalysis.objects.filter(Exists(analysed))
        .exclude(status=GelAnalysis.Status.REJECTED)
        .select_related("gel_image__assay")
        .prefetch_related(
            Prefetch(
                "lanes", queryset=Lane.objects.select_related("densitometry_summary").order_by("lane_number", "pk")
            )
        )
        .order_by("-created_at")[:limit]
    )
    gels = []
    for analysis in analyses:
        image = analysis.gel_image
        measures_purity = image_measures_purity(image)
        lanes = []
        for lane in analysis.lanes.all():
            summary = _summary_of(lane)
            purity = published_purity(summary) if measures_purity and summary is not None else None
            lanes.append(
                {
                    "id": lane.pk,
                    "number": lane.lane_number,
                    "type": lane.lane_type,
                    "type_label": lane.get_lane_type_display(),
                    "sample": lane.sample_name or "",
                    "analysed": summary is not None,
                    "purity": round(purity, 1) if purity is not None else None,
                }
            )
        gels.append(
            {
                "id": str(analysis.pk),
                "name": analysis.name or "",
                "filename": image.original_filename,
                "assay": assay_label(image),
                "status": analysis.get_status_display(),
                "created": timezone.localtime(analysis.created_at).date().isoformat(),
                "url": reverse("gel_analyzer:analysis_detail", kwargs={"pk": analysis.pk}),
                "lanes": lanes,
            }
        )
    return gels


def _requested_lanes(request) -> list[int]:
    """The lane ids of ``?lanes=1,2,3`` (or repeated ``lanes=``), in order, without duplicates."""
    seen, ids = set(), []
    for chunk in request.GET.getlist("lanes"):
        for part in chunk.split(","):
            part = part.strip()
            if part.isdigit() and int(part) not in seen:
                seen.add(int(part))
                ids.append(int(part))
    return ids[:MAX_LANES]


@login_required
def gel_dashboard_view(request):
    """The gel dashboard page. ``?lanes=`` pre-ticks lanes, so a selection can be bookmarked."""
    gels = pickable_gels()
    context = {
        "page_title": "Gel dashboard",
        "gel_count": len(gels),
        "gels_json": script_json(gels),
        "selected_json": script_json(_requested_lanes(request)),
        "max_lanes": MAX_LANES,
        "purity_thresholds_json": script_json({"good": PURITY_GOOD, "fair": PURITY_FAIR}),
    }
    return render(request, "gel_analyzer/dashboard/gels.html", context)
