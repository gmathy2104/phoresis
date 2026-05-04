"""
DRF API Tests for Gel Analyzer.

Tests the formal REST API at /api/v1/.
Uses existing fixtures from conftest.py.

Run with: pytest src/gel_analyzer/tests/test_drf_api.py -v
"""

import pytest
from rest_framework import status

pytestmark = pytest.mark.integration


class TestGelImageAPI:
    """Tests for GelImage DRF endpoints."""

    def test_list_images(self, authenticated_api_client, gel_image):
        url = "/api/v1/images/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) >= 1

    def test_retrieve_image(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(gel_image.id)
        assert "display_file_url" in response.data
        assert "thumbnail_url" in response.data

    def test_retrieve_image_has_dimensions(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.data["width"] == 400
        assert response.data["height"] == 500

    def test_delete_image(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_schema_accessible(self, authenticated_api_client):
        url = "/api/schema/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_swagger_ui_accessible(self, authenticated_api_client):
        url = "/api/docs/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK


class TestGelAnalysisAPI:
    """Tests for GelAnalysis DRF endpoints."""

    def test_list_analyses(self, authenticated_api_client, gel_analysis):
        url = "/api/v1/analyses/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data

    def test_retrieve_analysis_full_tree(self, authenticated_api_client, complete_analysis):
        url = f"/api/v1/analyses/{complete_analysis.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "gel_image" in response.data
        assert "lanes" in response.data
        assert len(response.data["lanes"]) > 0

    def test_retrieve_analysis_has_image_urls(self, authenticated_api_client, complete_analysis):
        url = f"/api/v1/analyses/{complete_analysis.id}/"
        response = authenticated_api_client.get(url)
        img = response.data["gel_image"]
        assert "display_file_url" in img
        assert "thumbnail_url" in img

    def test_create_analysis(self, authenticated_api_client, gel_image):
        url = "/api/v1/analyses/"
        data = {"gel_image": str(gel_image.id), "name": "API Analysis"}
        response = authenticated_api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED

    def test_analysis_status_transition(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"
        response = authenticated_api_client.post(url, {"status": "IN_PROGRESS"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_analysis_invalid_transition(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"
        response = authenticated_api_client.post(url, {"status": "APPROVED"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_analysis(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/"
        response = authenticated_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestLaneAPI:
    """Tests for Lane DRF endpoints."""

    def test_retrieve_lane(self, authenticated_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["lane_type"] == "SAMPLE"
        assert "bands" in response.data

    def test_update_lane(self, authenticated_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = authenticated_api_client.patch(url, {"sample_name": "Updated"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_delete_lane(self, authenticated_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = authenticated_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestBandAPI:
    """Tests for Band DRF endpoints."""

    def test_retrieve_band(self, authenticated_api_client, band):
        url = f"/api/v1/bands/{band.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "bbox" in response.data
        assert response.data["estimated_mw_kda"] == 55.0

    def test_delete_band(self, authenticated_api_client, band):
        url = f"/api/v1/bands/{band.id}/"
        response = authenticated_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestCalibrationAPI:
    """Tests for Calibration endpoint on GelAnalysisViewSet."""

    def test_calibration_not_found(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/calibration/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDetectionAPI:
    """Tests for Detection endpoints on GelAnalysisViewSet."""

    def test_detection_params_defaults(self, authenticated_api_client, db):
        url = "/api/v1/analyses/detection-params/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "smoothing_window" in response.data


class TestDensitometryAPI:
    """Tests for Densitometry endpoints on GelAnalysisViewSet."""

    def test_densitometry_results_not_found(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/densitometry/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestLadderTemplateAPI:
    """Tests for LadderTemplate DRF endpoints."""

    def test_list_templates(self, authenticated_api_client, db):
        url = "/api/v1/ladder-templates/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_default_template_not_found(self, authenticated_api_client, db):
        url = "/api/v1/ladder-templates/default/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestSavedComparisonAPI:
    """Tests for SavedComparison DRF endpoints."""

    def test_list_comparisons(self, authenticated_api_client, db):
        url = "/api/v1/comparisons/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
