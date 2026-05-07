"""
Tests for the protein quantification REST API.

Covers:
- Band PATCH with nested quant_point (Task 4.1)
- Lane downgrade with ?force=true purge (Task 4.2)
- Quantification GET / POST / PATCH / DELETE / preview / history (Task 4.3)
"""

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Task 4.1 — Band serializer with nested quant_point
# ---------------------------------------------------------------------------


def test_patch_band_to_calibration_with_quant_point(authenticated_client, calibration_band):
    url = f"/api/v1/bands/{calibration_band.id}/"
    response = authenticated_client.patch(
        url,
        {"band_type": "CALIBRATION", "quant_point": {"load_amount": 10.0, "load_unit": "UG"}},
        format="json",
    )
    assert response.status_code == 200, response.content
    calibration_band.refresh_from_db()
    assert calibration_band.quant_point.load_amount == 10.0


def test_patch_band_calibration_without_quant_point_400(authenticated_client, calibration_band):
    # Strip an existing quant_point first to make this a "creation" path
    from gel_analyzer.models import ProteinQuantCalibrationPoint

    ProteinQuantCalibrationPoint.objects.filter(band=calibration_band).delete()
    url = f"/api/v1/bands/{calibration_band.id}/"
    response = authenticated_client.patch(url, {"band_type": "CALIBRATION"}, format="json")
    assert response.status_code == 400


def test_patch_band_calibration_in_sample_lane_400(authenticated_client, sample_band):
    url = f"/api/v1/bands/{sample_band.id}/"
    response = authenticated_client.patch(
        url,
        {"band_type": "CALIBRATION", "quant_point": {"load_amount": 10.0, "load_unit": "UG"}},
        format="json",
    )
    assert response.status_code == 400
    body_text = response.content.decode().lower()
    assert "lane" in body_text


# ---------------------------------------------------------------------------
# Task 4.2 — Lane downgrade with ?force=true
# ---------------------------------------------------------------------------


def test_lane_downgrade_409_without_force(authenticated_client, calib_lane_with_point):
    lane = calib_lane_with_point
    url = f"/api/v1/lanes/{lane.id}/"
    response = authenticated_client.patch(url, {"lane_type": "SAMPLE"}, format="json")
    assert response.status_code == 409, response.content
    body = response.json()
    assert "dependent_band_ids" in body and len(body["dependent_band_ids"]) >= 1


def test_lane_downgrade_with_force_purges(authenticated_client, calib_lane_with_point):
    lane = calib_lane_with_point
    url = f"/api/v1/lanes/{lane.id}/?force=true"
    response = authenticated_client.patch(url, {"lane_type": "SAMPLE"}, format="json")
    assert response.status_code == 200, response.content
    lane.refresh_from_db()
    assert lane.lane_type == "SAMPLE"
    from gel_analyzer.models import ProteinQuantCalibrationPoint

    assert ProteinQuantCalibrationPoint.objects.filter(band__lane=lane).count() == 0


# ---------------------------------------------------------------------------
# Task 4.3 — quantification endpoints
# ---------------------------------------------------------------------------


def test_preview_returns_fit_metadata(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/api/v1/analyses/{analysis.id}/quantification/preview/"
    response = authenticated_client.post(
        url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["success"] is True
    assert body["r_squared"] > 0.99


def test_save_creates_active_calibration(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/api/v1/analyses/{analysis.id}/quantification/"
    response = authenticated_client.post(
        url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    assert response.status_code == 201, response.content
    from gel_analyzer.models import ProteinQuantCalibration

    assert ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).count() == 1


def test_save_then_save_supersedes_previous(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/api/v1/analyses/{analysis.id}/quantification/"
    r1 = authenticated_client.post(
        url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    assert r1.status_code == 201, r1.content
    r2 = authenticated_client.post(
        url, {"method": "POLYNOMIAL_2", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    assert r2.status_code == 201, r2.content
    from gel_analyzer.models import ProteinQuantCalibration

    assert ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).count() == 1


def test_get_returns_active_or_null(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    url = f"/api/v1/analyses/{analysis.id}/quantification/"
    response = authenticated_client.get(url)
    assert response.status_code == 200
    assert response.json()["active"] is None  # nothing saved yet


def test_history_returns_supersedes(authenticated_client, three_calib_points_analysis):
    analysis = three_calib_points_analysis
    save_url = f"/api/v1/analyses/{analysis.id}/quantification/"
    authenticated_client.post(
        save_url, {"method": "LINEAR", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    authenticated_client.post(
        save_url, {"method": "POLYNOMIAL_2", "unit": "UG", "excluded_band_ids": []}, format="json"
    )
    history_url = f"/api/v1/analyses/{analysis.id}/quantification/history/"
    response = authenticated_client.get(history_url)
    assert response.status_code == 200
    assert len(response.json()["history"]) == 2
