"""
Tests for Gel Analyzer non-DRF API endpoints (the legacy ``/api/...`` JSON
views, not the DRF v1 surface).
"""

import json

import pytest

from django.urls import reverse


@pytest.mark.django_db
class TestAPILanes:
    """Tests for api_lanes endpoint."""

    def test_get_lanes_requires_login(self, client, gel_analysis):
        """Test that GET requires authentication."""
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_get_lanes_authenticated(self, client, test_user, gel_analysis):
        """Test GET returns lanes."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert "lanes" in data
        assert data["analysis_id"] == str(gel_analysis.pk)

    def test_get_lanes_with_bands(self, client, test_user, gel_analysis, sample_lane, band):
        """Test GET returns lanes with nested bands."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data["lanes"]) == 1
        assert len(data["lanes"][0]["bands"]) == 1

    def test_post_lane_creates_lane(self, client, test_user, gel_analysis):
        """Test POST creates a new lane."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "x": 100,
                    "y": 50,
                    "width": 50,
                    "height": 400,
                    "lane_number": 1,
                    "lane_type": "SAMPLE",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["lane"]["lane_number"] == 1


@pytest.mark.django_db
class TestAPILaneDetail:
    """Tests for api_lane_detail endpoint."""

    def test_get_lane_detail(self, client, test_user, sample_lane):
        """Test GET returns lane details."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": sample_lane.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["lane"]["lane_number"] == sample_lane.lane_number

    def test_put_lane_updates(self, client, test_user, sample_lane):
        """Test PUT updates lane properties."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": sample_lane.pk})
        response = client.put(
            url,
            data=json.dumps(
                {
                    "sample_name": "Updated Sample",
                    "notes": "Test notes",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lane"]["sample_name"] == "Updated Sample"

    def test_delete_lane(self, client, test_user, sample_lane, gel_analysis):
        """Test DELETE removes lane."""
        client.force_login(test_user)
        pk = sample_lane.pk
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": pk})
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()["success"] is True

        from gel_analyzer.models import Lane

        assert not Lane.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestAPILaneBands:
    """Tests for api_lane_bands endpoint."""

    def test_post_band_creates_band(self, client, test_user, sample_lane):
        """Test POST creates a new band."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_bands", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "polygon": [[50, 100], [90, 100], [90, 120], [50, 120]],
                    "position_y": 110,
                    "label": "Test Band",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["band"]["label"] == "Test Band"


@pytest.mark.django_db
class TestAPIBandDetail:
    """Tests for api_band_detail endpoint."""

    def test_get_band_detail(self, client, test_user, band):
        """Test GET returns band details."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": band.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert float(data["band"]["estimated_mw_kda"]) == 55.0

    def test_put_band_updates(self, client, test_user, band):
        """Test PUT updates band properties."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": band.pk})
        response = client.put(
            url,
            data=json.dumps(
                {
                    "label": "Main Product",
                    "estimated_mw_kda": 60.0,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["band"]["label"] == "Main Product"

    def test_delete_band(self, client, test_user, band, sample_lane):
        """Test DELETE removes band."""
        client.force_login(test_user)
        pk = band.pk
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": pk})
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()["success"] is True

        from gel_analyzer.models import Band

        assert not Band.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestAPIAnalysisData:
    """Tests for api_analysis_data endpoint."""

    def test_get_analysis_data(self, client, test_user, complete_analysis):
        """Test GET returns full analysis data."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_analysis_data", kwargs={"pk": complete_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert "analysis" in data
        assert "gel_image" in data
        assert "lanes" in data
        assert len(data["lanes"]) > 0
