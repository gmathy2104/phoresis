"""
Regression tests for the lane/sample comparison view's URL-parameter parsing.

The view docstring promises both `?lanes=1&lanes=2&lanes=3` (multi-param) and
`?lanes=1,2,3` (comma-joined) — but the original implementation only handled
the multi-param form, so a comma-form URL would 500 with:

    Error processing lane 1146,1147,...: Field 'id' expected a number but got
    '1146,1147,...'

The new `_parse_id_param` helper unifies both forms and silently filters
non-numeric junk.
"""

import json

import pytest

from django.urls import reverse

from gel_analyzer.models import SavedComparison, SavedComparisonLane


def URL():
    return reverse("gel_analyzer:sample_comparison")


@pytest.mark.django_db
def test_comparison_view_lanes_multi_param(client, test_user, sample_lane):
    """Standard form ?lanes=1&lanes=2 still works."""
    client.force_login(test_user)
    resp = client.get(URL(), {"lanes": [str(sample_lane.pk)]})
    assert resp.status_code == 200


@pytest.mark.django_db
def test_comparison_view_lanes_comma_joined(client, test_user, sample_lane, ladder_lane):
    """Comma form ?lanes=1,2 must NOT raise (was producing 500 in production)."""
    client.force_login(test_user)
    resp = client.get(URL(), {"lanes": f"{sample_lane.pk},{ladder_lane.pk}"})
    assert resp.status_code == 200


@pytest.mark.django_db
def test_comparison_view_lanes_mixed_format(client, test_user, sample_lane, ladder_lane):
    """Mixed: ?lanes=1&lanes=2,3 should split + flatten."""
    client.force_login(test_user)
    resp = client.get(URL() + f"?lanes={sample_lane.pk}&lanes={ladder_lane.pk}")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_comparison_view_lanes_garbage_filtered(client, test_user, sample_lane):
    """Non-numeric tokens are silently filtered (no 500, page renders)."""
    client.force_login(test_user)
    resp = client.get(URL(), {"lanes": f"abc,{sample_lane.pk},xyz"})
    assert resp.status_code == 200


@pytest.mark.django_db
def test_comparison_view_no_params(client, test_user):
    """Empty params → empty comparison page."""
    client.force_login(test_user)
    resp = client.get(URL())
    assert resp.status_code == 200


@pytest.mark.django_db
def test_comparison_view_saved_comparison_id_that_is_not_a_uuid(client, test_user):
    """?comparison=<not a uuid> is ignored like an inaccessible comparison (2026-10-12): the primary key is a
    UUIDField, whose lookup raises ValidationError -- an exception the view did not catch, so a hand-typed
    or truncated link answered 500."""
    client.force_login(test_user)
    resp = client.get(URL(), {"comparison": "not-a-uuid"})
    assert resp.status_code == 200
    assert resp.context["saved_comparison_json"] == "null"


@pytest.mark.django_db
def test_comparison_view_opens_a_saved_comparison_for_its_owner_or_when_public_never_anothers_private(
    client, test_user, sample_lane, django_user_model
):
    """?comparison=<uuid> loads the saved comparison only when the user may read it -- theirs, or a public
    one (access.user_can_read_saved_comparison, the rule of the API and the report route). Another user's
    PRIVATE comparison is ignored like a missing one: no name, no lanes on the page. No test held this gate
    before 2026-10-12 (the control tower's mutant opening it stayed green)."""
    other = django_user_model.objects.create_user(username="other_user", password="x")

    def saved(owner, public):
        comparison = SavedComparison.objects.create(
            name=f"{owner.username} {public}", created_by=owner, is_public=public
        )
        SavedComparisonLane.objects.create(saved_comparison=comparison, lane=sample_lane, order=0)
        return comparison

    mine, theirs_public, theirs_private = saved(test_user, False), saved(other, True), saved(other, False)
    client.force_login(test_user)

    def loaded(comparison):
        response = client.get(URL(), {"comparison": str(comparison.pk)})
        assert response.status_code == 200
        info = json.loads(response.context["saved_comparison_json"])
        return (info["id"] if info else None), [item["lane"]["id"] for item in response.context["items_data"]]

    assert loaded(mine) == (str(mine.pk), [sample_lane.pk])  # the owner opens their private comparison
    assert loaded(theirs_public) == (str(theirs_public.pk), [sample_lane.pk])
    assert loaded(theirs_private) == (None, [])
