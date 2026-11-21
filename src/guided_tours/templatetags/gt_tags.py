"""``{% gt_launcher %}`` -- the compass and the tour of the page.

Called from the two page chromes: the top bar of the application pages (``components/_topbar.html``) and the
identity row of the gel workbench (``gel_analyzer/workbench/_identity.html``, ``variant="workbench"``). The page is
known by ``context.template_name``, the name of the template the view rendered (Django sets it on the top-level render
and keeps it through ``{% extends %}`` and ``{% include %}``). A page without a tour gets nothing. Decoration must
never break the page it decorates: any failure is logged and the page renders without a tour.

Ported from ds-hub-django (``guided_tours/templatetags/gt_tags.py``), where the guide's ``?`` button calls it.
"""

from django import template
from django.db import transaction
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse

from guided_tours import registry
from guided_tours.models import TourProgress
from phoresis_core.logging_config import get_logger
from phoresis_core.safe_json import script_json

logger = get_logger(__name__)
register = template.Library()

# A page may carry two chromes: one launcher per request. A flag on the request, since each template render gets an
# isolated render_context.
_DONE = "_gt_launcher_done"


def _guide_url(tour):
    """The user guide a tour's steps link to ("More in the guide"), when the project serves one. Phoresis has no
    guide pages yet, so its tours name none; the hook stays for the day it has."""
    if not tour.guide_app or not tour.guide_page:
        return None
    try:
        return reverse("help:page", kwargs={"app": tour.guide_app, "page": tour.guide_page})
    except NoReverseMatch:
        return None


@register.simple_tag(takes_context=True)
def gt_launcher(context, variant=""):
    request = context.get("request")
    template_name = getattr(context, "template_name", None)
    try:
        tour = registry.tour_for_template(template_name)
        if tour is None or request is None or getattr(request, _DONE, False):
            return ""
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return ""
        setattr(request, _DONE, True)
        # In a savepoint: a failed query (the table not migrated yet) inside a view's own transaction would otherwise
        # break every query the view runs after this tag, and "the page renders without a tour" would not hold.
        with transaction.atomic():
            progress = TourProgress.objects.filter(user=user, tour_id=tour.tour_id).only("version").first()
        island = {
            "tour": tour.as_client_dict(),
            "seen_version": progress.version if progress else None,
            "urls": {"progress": reverse("guided_tours:progress"), "events": reverse("guided_tours:events")},
            "csrf": get_token(request),
            "guide_url": _guide_url(tour),
        }
        return render_to_string(
            "guided_tours/_launcher.html",
            {"variant": variant, "island": script_json(island)},
        )
    except Exception:  # noqa: BLE001 -- a tour is decoration: the page renders without it
        logger.exception(f"guided tours: launcher failed on {template_name}")
        return ""
