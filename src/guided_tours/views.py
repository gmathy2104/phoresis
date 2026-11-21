"""The two endpoints of the tour runner: what a person has seen, and what they did; and the /tours/ page.

Both endpoints answer JSON, ``401`` for an anonymous caller -- never ``login_required``'s redirect, which ``fetch``
would follow to a 200 login page and read as saved. Both refuse an unknown tour or a version other than the current
one, so the tables only hold rows about tours that exist. The page is an ordinary page.

Ported from ds-hub-django (``guided_tours/views.py``).
"""

import json

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from guided_tours import registry
from guided_tours.models import TourEvent, TourProgress

MAX_DETAIL_BYTES = 2048
DETAIL_KEYS = {"reason", "trigger", "left_out"}


def _refuse(status, error):
    return JsonResponse({"ok": False, "error": error}, status=status)


def _read(request):
    """``(body, tour, error_response)``: the JSON body and its tour, or the refusal to send."""
    if not request.user.is_authenticated:
        return None, None, _refuse(401, "login required")
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None, None, _refuse(400, "the body is not JSON")
    if not isinstance(body, dict):
        return None, None, _refuse(400, "the body is not a JSON object")
    tour = registry.get(body.get("tour_id"))
    if tour is None:
        return None, None, _refuse(400, "unknown tour")
    if body.get("version") != tour.version:
        return None, None, _refuse(400, f"tour {tour.tour_id} is at version {tour.version}")
    return body, tour, None


@require_POST
def progress_view(request):
    body, tour, refusal = _read(request)
    if refusal:
        return refusal
    status = body.get("status")
    if status not in TourProgress.Status.values:
        return _refuse(400, "status is completed or dismissed")
    # One row per (user, tour). A newer version replaces it; within a version COMPLETED wins: a replay closed early
    # does not turn a completed tour back into dismissed -- under a row lock, so two tabs posting at once cannot either.
    with transaction.atomic():
        row = TourProgress.objects.select_for_update().filter(user=request.user, tour_id=tour.tour_id).first()
        if row is None:
            try:
                with transaction.atomic():
                    row = TourProgress.objects.create(
                        user=request.user, tour_id=tour.tour_id, version=tour.version, status=status
                    )
            except IntegrityError:  # the other tab created it between the read and the insert
                row = TourProgress.objects.select_for_update().get(user=request.user, tour_id=tour.tour_id)
        if row.version != tour.version or (row.status != status and status == TourProgress.Status.COMPLETED):
            row.version, row.status = tour.version, status
            row.save(update_fields=["version", "status", "updated_at"])
    return JsonResponse({"ok": True, "status": row.status})


@require_POST
def events_view(request):
    body, tour, refusal = _read(request)
    if refusal:
        return refusal
    event = body.get("event")
    if event not in TourEvent.Event.values:
        return _refuse(400, "unknown event")
    step_key = body.get("step_key") or ""
    if not isinstance(step_key, str) or len(step_key) > 64:
        return _refuse(400, "step_key is a text of 64 characters at most")
    step_index = body.get("step_index")
    if step_index is not None and (
        not isinstance(step_index, int) or isinstance(step_index, bool) or not 0 <= step_index < len(tour.steps)
    ):
        return _refuse(400, "step_index is the index of one of the tour's steps")
    detail = body.get("detail") or {}
    if (
        not isinstance(detail, dict)
        or set(detail) - DETAIL_KEYS
        or len(json.dumps(detail).encode("utf-8")) > MAX_DETAIL_BYTES
    ):
        return _refuse(400, f"detail holds {', '.join(sorted(DETAIL_KEYS))} only, 2 KB at most")
    TourEvent.objects.create(
        user=request.user,
        tour_id=tour.tour_id,
        version=tour.version,
        event=event,
        step_key=step_key,
        step_index=step_index,
        detail=detail,
    )
    return HttpResponse(status=204)


@login_required
@require_GET
def index_view(request):
    """/tours/ -- every tour, grouped by app, with a Start link when it has one."""
    from guided_tours.discover import tour_listing

    groups = {}
    for row in tour_listing(request.user):
        groups.setdefault(row["app_name"], []).append(row)
    rows = [row for group in groups.values() for row in group]
    return render(
        request,
        "guided_tours/index.html",
        {
            "page_title": "Guided tours",
            "groups": [{"name": name, "tours": tours} for name, tours in groups.items()],
            "taken": sum(row["status"] == "taken" for row in rows),
            "total": len(rows),
        },
    )
