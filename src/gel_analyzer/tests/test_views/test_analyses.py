"""Tests for gel_analyzer analysis views.

Phase 3 baseline (list/create smoke tests using ``UserFactory``) plus
detail / annotate / per-class coverage ported from
``$DSHUB/gel_analyzer/tests/test_views/test_analyses.py``.

The Phase 3 tests deliberately use a local ``gel_image`` fixture so they do
not pull in the heavier ``test_user``/``gel_image``/``gel_analysis`` fixtures
from ``conftest.py``. The ported class-based tests rely on those richer
fixtures.
"""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory
from gel_analyzer.models import GelAnalysis, GelImage

# =============================================================================
# Phase 3 smoke tests (kept intact)
# =============================================================================


@pytest.fixture
def gel_image_factory_user(db):
    """Phase-3 minimal GelImage created via UserFactory.

    Renamed (was ``gel_image``) so it does not collide with the conftest
    fixture used by the ported class-based tests below.
    """
    user = UserFactory(username="ga_user")
    return GelImage.objects.create(
        original_filename="x.png",
        file_format=GelImage.FileFormat.PNG,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=user,
    )


@pytest.mark.django_db
def test_analysis_list_returns_200(client, gel_image_factory_user) -> None:
    user = UserFactory(username="al_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_list"))
    assert response.status_code == 200
    assert b"Analyses" in response.content


@pytest.mark.django_db
def test_analysis_create_get_returns_200(client, gel_image_factory_user) -> None:
    user = UserFactory(username="ac_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image_factory_user.pk}))
    assert response.status_code == 200
    assert b"New analysis" in response.content


# =============================================================================
# Ported class-based tests (analysis list / create / detail / annotate)
# =============================================================================


@pytest.mark.django_db
class TestAnalysisListView:
    """Tests for analysis_list_view."""

    def test_list_view_requires_login(self, client):
        """Test that list view requires authentication."""
        url = reverse("gel_analyzer:analysis_list")
        response = client.get(url)
        assert response.status_code == 302

    def test_list_view_authenticated(self, client, test_user):
        """Test that authenticated users can access list view."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_list")
        response = client.get(url)
        assert response.status_code == 200
        assert "analyses" in response.context

    def test_list_view_shows_analyses(self, client, test_user, gel_analysis):
        """Test that list view shows analyses."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_list")
        response = client.get(url)
        assert response.status_code == 200
        assert gel_analysis.name in response.content.decode()

    def test_list_view_filter_by_status(self, client, test_user, gel_analysis):
        """Test filtering by status."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_list") + "?status=DRAFT"
        response = client.get(url)
        assert response.status_code == 200
        assert gel_analysis.name in response.content.decode()


@pytest.mark.django_db
class TestAnalysisCreateView:
    """Tests for analysis_create_view."""

    def test_create_view_requires_login(self, client, gel_image):
        """Test that create view requires authentication."""
        url = reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_create_view_get(self, client, test_user, gel_image):
        """Test GET request shows form."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "form" in response.context
        assert "gel_image" in response.context

    def test_create_view_post_valid(self, client, test_user, gel_image):
        """Test POST request creates analysis."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image.pk})
        response = client.post(
            url,
            {
                "name": "New Test Analysis",
                "notes": "Test notes",
            },
        )
        # Should redirect after create.
        assert response.status_code == 302
        assert GelAnalysis.objects.filter(name="New Test Analysis").exists()


@pytest.mark.django_db
class TestAnalysisDetailView:
    """Tests for analysis_detail_view."""

    def test_detail_view_requires_login(self, client, gel_analysis):
        """Test that detail view requires authentication."""
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_detail_view_authenticated(self, client, test_user, gel_analysis):
        """Test that authenticated users can access detail view."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "analysis" in response.context
        assert response.context["analysis"] == gel_analysis


@pytest.mark.django_db
class TestAnalysisAnnotateView:
    """Tests for analysis_annotate_view."""

    def test_annotate_view_requires_login(self, client, gel_analysis):
        """Test that annotate view requires authentication."""
        url = reverse("gel_analyzer:analysis_annotate", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_annotate_view_editable_analysis(self, client, test_user, gel_analysis):
        """Test annotate view for editable analysis."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_annotate", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "analysis" in response.context

    def test_annotate_view_updates_status(self, client, test_user, gel_analysis):
        """Test that opening annotate view updates status to IN_PROGRESS."""
        assert gel_analysis.status == "DRAFT"
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_annotate", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200

        gel_analysis.refresh_from_db()
        assert gel_analysis.status == "IN_PROGRESS"

    def test_annotate_view_completed_analysis_redirects(self, client, test_user, gel_analysis):
        """Test that completed analysis redirects to detail view."""
        gel_analysis.status = "COMPLETED"
        gel_analysis.save()

        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_annotate", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 302
        assert "analyses" in response.url and "annotate" not in response.url
