"""The tour files on disk, held to what the pages really carry.

A tour aims at ``data-tour`` attributes: a renamed attribute, a moved template or a renamed URL drops a step (or a
whole tour) without a sound, since the runner simply leaves out what it cannot find. These tests are the lint
ds-hub-django runs at every push (``tools/lint/check_guided_tours.py``), minus its guide-anchor check: Phoresis
tours link to no user guide.
"""

import re
from pathlib import Path

import pytest

from django.apps import apps
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import reverse

from guided_tours import registry
from guided_tours.discover import entry_url, tour_listing
from guided_tours.tour_schema import read_tours

SRC = Path(__file__).resolve().parents[2]
DATA_TOUR = re.compile(r'data-tour="([a-z0-9-]+)"')


def _keys_on_pages():
    """Every ``data-tour`` value written in a template or a script of the project."""
    keys = set()
    for pattern in ("*/templates/**/*.html", "*/static/**/*.js"):
        for path in SRC.glob(pattern):
            if "vendor" not in path.parts:
                keys.update(DATA_TOUR.findall(path.read_text(encoding="utf-8", errors="replace")))
    return keys


def test_no_tour_file_is_refused():
    tours, refusals = read_tours(cfg.path for cfg in apps.get_app_configs())
    assert refusals == []
    assert len(tours) >= 11, "the registry would hold too few tours: it read the wrong folders"
    assert {tour.tour_id for tour in tours} == {tour.tour_id for tour in registry.all_tours()}


def test_every_tour_names_templates_that_exist():
    missing = []
    for tour in registry.all_tours():
        for name in tour.templates:
            try:
                get_template(name)
            except TemplateDoesNotExist:
                missing.append(f"{tour.tour_id}: {name}")
    assert missing == []


def test_every_step_aims_at_an_attribute_a_page_carries():
    on_pages = _keys_on_pages()
    lost = [
        f"{tour.tour_id}: {step.key}"
        for tour in registry.all_tours()
        for step in tour.steps
        if step.key not in on_pages
    ]
    assert lost == []


def test_every_attribute_belongs_to_a_tour():
    """A ``data-tour`` no tour names is a step someone forgot to write, or the leftover of a removed one."""
    in_tours = {step.key for tour in registry.all_tours() for step in tour.steps}
    assert sorted(_keys_on_pages() - in_tours) == []


def test_every_tour_entry_reverses():
    """A renamed URL would drop its tour's Start link from /tours/ without a sound."""
    with_entry = [tour for tour in registry.all_tours() if tour.entry]
    assert len(with_entry) >= 6
    assert [tour.tour_id for tour in with_entry if not entry_url(tour)] == []


@pytest.mark.django_db
def test_a_page_with_a_tour_gets_the_compass_and_its_island(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="tour_taker", password="pw-not-used"))
    page = client.get(reverse("dashboard:home")).content.decode()
    assert "data-gt-launch" in page
    assert '<script type="application/json" id="gt-tour-data">' in page
    assert '"tour_id": "home"' in page

    # a page without a tour gets nothing: no button, no Driver.js
    profile = client.get(reverse("accounts:profile")).content.decode()
    assert "data-gt-launch" not in profile and "driver.js.iife.js" not in profile


@pytest.mark.django_db
def test_the_tours_page_lists_every_tour_with_its_status(client, django_user_model):
    from guided_tours.models import TourProgress

    user = django_user_model.objects.create_user(username="tour_taker", password="pw-not-used")
    home = registry.get("home")
    TourProgress.objects.create(user=user, tour_id=home.tour_id, version=home.version, status="completed")

    rows = {row["tour_id"]: row for row in tour_listing(user)}
    assert rows["home"]["status"] == "taken"
    assert rows["ga.image-list"]["status"] == "not-yet"
    assert rows["ga.image-list"]["url"].endswith("?tour=ga.image-list")
    assert rows["ga.image-page"]["url"] == ""  # the page of one record: started from its own compass

    client.force_login(user)
    page = client.get(reverse("guided_tours:index")).content.decode()
    assert "You took <b>1</b>" in page
    assert "?tour=ga.gel-dashboard" in page
