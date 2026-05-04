"""Tests for Saved Comparison API endpoints."""

import json

import pytest

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from gel_analyzer.models import SavedComparison, SavedComparisonLane

User = get_user_model()


@pytest.fixture
def other_user(db):
    """Create a second test user."""
    return User.objects.create_user(username="other_user", email="other@example.com", password="testpass123")


@pytest.fixture
def auth_client(test_user):
    """Create an authenticated test client."""
    client = Client()
    client.force_login(test_user)
    return client


@pytest.fixture
def other_client(other_user):
    """Create an authenticated client for the other user."""
    client = Client()
    client.force_login(other_user)
    return client


@pytest.fixture
def saved_comparison(test_user, sample_lane):
    """Create a saved comparison with one lane."""
    comp = SavedComparison.objects.create(
        name="Test Comparison",
        description="A test comparison",
        created_by=test_user,
    )
    SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
    return comp


@pytest.mark.django_db
class TestSavedComparisonListAPI:
    """Tests for GET/POST /api/comparisons/."""

    def test_create_comparison(self, auth_client, sample_lane):
        """Test creating a new saved comparison."""
        response = auth_client.post(
            reverse("gel_analyzer:api_saved_comparisons"),
            data=json.dumps(
                {
                    "name": "My Comparison",
                    "description": "Test desc",
                    "lane_ids": [sample_lane.pk],
                    "is_public": True,
                    "view_settings": {"normalization_mode": "total"},
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Comparison"
        assert data["description"] == "Test desc"
        assert data["is_public"] is True
        assert data["lane_count"] == 1
        assert data["view_settings"]["normalization_mode"] == "total"
        assert len(data["lanes"]) == 1

    def test_create_requires_name(self, auth_client, sample_lane):
        """Test that name is required."""
        response = auth_client.post(
            reverse("gel_analyzer:api_saved_comparisons"),
            data=json.dumps({"lane_ids": [sample_lane.pk]}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Name" in response.json()["error"]

    def test_create_requires_lanes(self, auth_client):
        """Test that at least one lane is required."""
        response = auth_client.post(
            reverse("gel_analyzer:api_saved_comparisons"),
            data=json.dumps({"name": "No Lanes"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "lane" in response.json()["error"].lower()

    def test_create_validates_lane_ids(self, auth_client):
        """Test that invalid lane IDs are rejected."""
        response = auth_client.post(
            reverse("gel_analyzer:api_saved_comparisons"),
            data=json.dumps(
                {
                    "name": "Bad IDs",
                    "lane_ids": [99999],
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Invalid" in response.json()["error"]

    def test_list_own_comparisons(self, auth_client, saved_comparison):
        """Test listing own comparisons."""
        response = auth_client.get(reverse("gel_analyzer:api_saved_comparisons"), {"filter": "mine"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        names = [c["name"] for c in data["results"]]
        assert "Test Comparison" in names

    def test_list_includes_public(self, auth_client, other_user, sample_lane):
        """Test that public comparisons from others are visible in 'all' mode."""
        # Create a public comparison by other user
        comp = SavedComparison.objects.create(
            name="Public From Other",
            created_by=other_user,
            is_public=True,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)

        response = auth_client.get(reverse("gel_analyzer:api_saved_comparisons"), {"filter": "all"})
        assert response.status_code == 200
        names = [c["name"] for c in response.json()["results"]]
        assert "Public From Other" in names

    def test_list_excludes_others_private(self, auth_client, other_user, sample_lane):
        """Test that private comparisons from others are not visible."""
        comp = SavedComparison.objects.create(
            name="Private From Other",
            created_by=other_user,
            is_public=False,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)

        response = auth_client.get(reverse("gel_analyzer:api_saved_comparisons"), {"filter": "all"})
        names = [c["name"] for c in response.json()["results"]]
        assert "Private From Other" not in names

    def test_list_search_by_name(self, auth_client, saved_comparison):
        """Test searching by name."""
        response = auth_client.get(reverse("gel_analyzer:api_saved_comparisons"), {"filter": "mine", "search": "Test"})
        assert response.status_code == 200
        assert response.json()["total"] >= 1

        response = auth_client.get(
            reverse("gel_analyzer:api_saved_comparisons"), {"filter": "mine", "search": "nonexistent_xyz"}
        )
        assert response.json()["total"] == 0

    def test_requires_login(self):
        """Test that unauthenticated requests redirect."""
        client = Client()
        response = client.get(reverse("gel_analyzer:api_saved_comparisons"))
        assert response.status_code == 302


@pytest.mark.django_db
class TestSavedComparisonDetailAPI:
    """Tests for GET/PUT/DELETE /api/comparisons/<uuid>/."""

    def test_get_own_comparison(self, auth_client, saved_comparison):
        """Test retrieving own comparison."""
        response = auth_client.get(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": saved_comparison.pk})
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Comparison"
        assert "lanes" in data
        assert len(data["lanes"]) == 1

    def test_get_public_comparison(self, other_client, test_user, sample_lane):
        """Test that other users can view public comparisons."""
        comp = SavedComparison.objects.create(
            name="Public",
            created_by=test_user,
            is_public=True,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)

        response = other_client.get(reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": comp.pk}))
        assert response.status_code == 200

    def test_get_others_private_returns_404(self, other_client, saved_comparison):
        """Test that other users cannot view private comparisons."""
        response = other_client.get(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": saved_comparison.pk})
        )
        assert response.status_code == 404

    def test_update_own_comparison(self, auth_client, saved_comparison):
        """Test updating own comparison."""
        response = auth_client.put(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": saved_comparison.pk}),
            data=json.dumps(
                {
                    "name": "Updated Name",
                    "is_public": True,
                    "description": "New desc",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["is_public"] is True
        assert data["description"] == "New desc"

    def test_update_others_returns_403(self, other_client, test_user, sample_lane):
        """Test that other users cannot update comparisons they don't own."""
        comp = SavedComparison.objects.create(
            name="Not Yours",
            created_by=test_user,
            is_public=True,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)

        response = other_client.put(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": comp.pk}),
            data=json.dumps({"name": "Hacked"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_update_lanes_reorders(self, auth_client, complete_analysis, test_user):
        """Test that updating lane_ids reorders lanes."""
        lanes = list(complete_analysis.lanes.filter(lane_type="SAMPLE").order_by("lane_number")[:3])
        assert len(lanes) >= 3

        comp = SavedComparison.objects.create(
            name="Reorder Test",
            created_by=test_user,
        )
        for i, lane in enumerate(lanes):
            SavedComparisonLane.objects.create(saved_comparison=comp, lane=lane, order=i)

        # Reverse the order
        reversed_ids = [lane.pk for lane in reversed(lanes)]
        response = auth_client.put(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": comp.pk}),
            data=json.dumps({"lane_ids": reversed_ids}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Verify order changed
        through_objs = list(SavedComparisonLane.objects.filter(saved_comparison=comp).order_by("order"))
        assert [t.lane_id for t in through_objs] == reversed_ids

    def test_delete_own_comparison(self, auth_client, saved_comparison):
        """Test deleting own comparison."""
        pk = saved_comparison.pk
        response = auth_client.delete(reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": pk}))
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert not SavedComparison.objects.filter(pk=pk).exists()

    def test_delete_others_returns_404(self, other_client, saved_comparison):
        """Test that other users cannot delete private comparisons."""
        response = other_client.delete(
            reverse("gel_analyzer:api_saved_comparison_detail", kwargs={"pk": saved_comparison.pk})
        )
        # Private comparison is not visible, so 404
        assert response.status_code == 404
        # Comparison still exists
        assert SavedComparison.objects.filter(pk=saved_comparison.pk).exists()
