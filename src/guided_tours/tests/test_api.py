"""The tour runner's two endpoints.

The registry holds a tour of this module (one ``setitem``: data, not behaviour): the endpoints only ask it whether a
tour exists and at which version.
"""

import json

import pytest

from django.urls import reverse

from guided_tours import registry, tour_schema
from guided_tours.models import TourEvent, TourProgress

TOUR = tour_schema.build(
    {
        "tour_id": "test.page",
        "version": 2,
        "templates": ["app/page.html"],
        "steps": [
            {"key": "a", "title": "A", "text": "The first."},
            {"key": "b", "title": "B", "text": "The second."},
        ],
    }
)


@pytest.fixture
def registered(monkeypatch):
    monkeypatch.setitem(registry._BY_ID, TOUR.tour_id, TOUR)
    return TOUR


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="tour_taker", password="pw-not-used")


@pytest.fixture
def authenticated_client(client, user):
    client.force_login(user)
    return client


def _post(client, name, body):
    return client.post(reverse(name), data=json.dumps(body), content_type="application/json")


@pytest.mark.django_db
def test_progress_is_kept_per_version_and_completed_wins_within_one(authenticated_client, user, registered):
    """A tab still on an older version cannot mark the new one as seen; a newer version replaces the row; within a
    version a replay closed early does not turn a completed tour back into dismissed; one row per user and tour."""
    TourProgress.objects.create(user=user, tour_id=TOUR.tour_id, version=1, status="completed")

    def post(version, status):
        return _post(
            authenticated_client,
            "guided_tours:progress",
            {"tour_id": TOUR.tour_id, "version": version, "status": status},
        )

    response = post(1, "dismissed")
    assert response.status_code == 400
    assert TourProgress.objects.values_list("version", "status").get(user=user) == (1, "completed")

    assert post(2, "dismissed").json() == {"ok": True, "status": "dismissed"}
    assert post(2, "completed").json()["status"] == "completed"
    assert post(2, "dismissed").json() == {"ok": True, "status": "completed"}
    assert TourProgress.objects.values_list("version", "status").get(user=user) == (2, "completed")


@pytest.mark.django_db
def test_the_runners_started_event_is_stored_with_its_detail(authenticated_client, user, registered):
    """The payload gt-tours.js sends when a tour starts, keys left out included: what one reads after a deploy to
    find a broken target. The runner ignores the answer, so a refusal here would lose the event silently."""
    detail = {"trigger": "button", "left_out": ["b"]}
    response = _post(
        authenticated_client,
        "guided_tours:events",
        {"tour_id": TOUR.tour_id, "version": 2, "event": "started", "detail": detail},
    )

    assert response.status_code == 204
    event = TourEvent.objects.get(user=user)
    assert (event.tour_id, event.version, event.event, event.detail) == (TOUR.tour_id, 2, "started", detail)


@pytest.mark.django_db
def test_an_anonymous_caller_gets_401_json_not_a_login_redirect(client, registered):
    """fetch() follows a redirect to the login page and reads its 200 as saved."""
    response = _post(client, "guided_tours:progress", {"tour_id": TOUR.tour_id, "version": 2, "status": "completed"})
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "login required"}
