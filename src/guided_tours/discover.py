"""The tours a person can open from a link: the /tours/ page.

A tour belongs to the app whose folder holds its file (``<app>/tours/<tour_id>.json``). Its link is its ``entry``
(a URL name without arguments) with ``?tour=<tour_id>``, which makes the runner start it on arrival; a tour without
one (the page of one record: an image, an analysis), or whose entry no longer reverses (logged), is listed without
a link.

Ported from ds-hub-django (``guided_tours/discover.py``) without its per-app access gate and its home widget:
in Phoresis every signed-in account opens every page.
"""

from __future__ import annotations

from pathlib import Path

from django.urls import NoReverseMatch, reverse

from guided_tours import registry
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def app_of(tour) -> str:
    """The app label of the folder that holds the tour's file."""
    return Path(tour.source).parent.parent.name if tour.source else ""


def entry_url(tour) -> str:
    """The address that opens the tour, or "" (no entry, or one that no longer reverses)."""
    if not tour.entry:
        return ""
    try:
        return f"{reverse(tour.entry)}?tour={tour.tour_id}"
    except NoReverseMatch:
        logger.warning(f"guided tours: {tour.tour_id} entry {tour.entry!r} does not reverse; listed without a link")
        return ""


def _title(tour) -> str:
    """'ga.image-list' -> 'Image list'; a word of two letters is an abbreviation: 'ga.mw-ladder' -> 'MW ladder'."""
    words = [word.upper() if len(word) <= 2 else word for word in tour.tour_id.split(".", 1)[-1].split("-")]
    title = " ".join(words)
    return title[:1].upper() + title[1:]


def tour_listing(user) -> list[dict]:
    """Every tour with its status for ``user``.

    ``status``: ``taken`` (completed at its current version), ``new`` (taken or skipped at an older version), or
    ``not-yet``.
    """
    from guided_tours.models import TourProgress
    from phoresis_core.navigation import nav_registry

    apps = nav_registry.get_apps()
    progress = {row.tour_id: row for row in TourProgress.objects.filter(user=user)}
    rows = []
    for tour in registry.all_tours():
        app = app_of(tour)
        seen = progress.get(tour.tour_id)
        if seen and seen.version >= tour.version and seen.status == TourProgress.Status.COMPLETED:
            status = "taken"
        elif seen and seen.version < tour.version:
            status = "new"
        else:
            status = "not-yet"
        rows.append(
            {
                "tour_id": tour.tour_id,
                "app_label": app,
                "app_name": apps[app]["display_name"] if app in apps else "Phoresis",
                "title": _title(tour),
                "steps": len(tour.steps),
                "url": entry_url(tour),
                "status": status,
            }
        )
    # the home's tour first, then in each app the tours that have a Start link (sorted() is stable)
    return sorted(rows, key=lambda row: (row["app_label"] != "dashboard", not row["url"]))
