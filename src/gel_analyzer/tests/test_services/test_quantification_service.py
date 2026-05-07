"""Tests for ProteinQuantCalibrationService.collect_*."""
import pytest

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    Lane,
    ProteinQuantCalibrationPoint,
)
from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

pytestmark = pytest.mark.django_db


@pytest.fixture
def calib_setup(sample_analysis, test_user):
    """Build a calibration lane + band + densitometry + point."""
    lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=10,
        lane_type=Lane.LaneType.CALIBRATION,
        x=0, y=0, width=50, height=200,
    )
    band = Band.objects.create(
        lane=lane, band_type=Band.BandType.CALIBRATION,
        position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
    )
    DensitometryResult.objects.create(
        band=band, peak_center_y=100, peak_amplitude=50,
        peak_sigma=5, fwhm=11.77, integrated_area=1000,
        corrected_area=1000, fit_r_squared=0.99, snr=20,
    )
    ProteinQuantCalibrationPoint.objects.create(
        band=band, load_amount=10.0, load_unit="UG", role="CALIBRATION",
    )
    return sample_analysis, lane, band


class TestCollectCalibrationPoints:
    def test_returns_band_with_densitometry(self, calib_setup):
        analysis, lane, band = calib_setup
        svc = ProteinQuantCalibrationService()
        points = svc.collect_calibration_points(analysis)
        assert len(points) == 1
        p = points[0]
        assert p.band_id == str(band.id)
        assert p.load_amount == 10.0
        assert p.corrected_area == 1000.0
        assert p.role == "CALIBRATION"

    def test_skips_band_without_densitometry(self, sample_analysis, test_user):
        lane = Lane.objects.create(
            analysis=sample_analysis, lane_number=11,
            lane_type=Lane.LaneType.CALIBRATION,
            x=0, y=0, width=50, height=200,
        )
        band = Band.objects.create(
            lane=lane, band_type=Band.BandType.CALIBRATION,
            position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=band, load_amount=10.0, load_unit="UG", role="CALIBRATION",
        )
        svc = ProteinQuantCalibrationService()
        points = svc.collect_calibration_points(sample_analysis)
        assert len(points) == 1
        assert points[0].corrected_area is None  # collected but flagged as missing

    def test_excludes_control_points(self, calib_setup, sample_analysis, test_user):
        # Add a CONTROL lane + band + point
        ctrl_lane = Lane.objects.create(
            analysis=sample_analysis, lane_number=12,
            lane_type=Lane.LaneType.CONTROL,
            x=0, y=0, width=50, height=200,
        )
        ctrl_band = Band.objects.create(
            lane=ctrl_lane, band_type=Band.BandType.CALIBRATION,
            position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        DensitometryResult.objects.create(
            band=ctrl_band, peak_center_y=100, peak_amplitude=50, peak_sigma=5,
            fwhm=11.77, integrated_area=900, corrected_area=900,
            fit_r_squared=0.99, snr=20,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=ctrl_band, load_amount=10.0, load_unit="UG", role="CONTROL",
        )
        svc = ProteinQuantCalibrationService()
        cal_points = svc.collect_calibration_points(sample_analysis)
        ctrl_points = svc.collect_control_points(sample_analysis)
        assert len(cal_points) == 1
        assert len(ctrl_points) == 1
        assert ctrl_points[0].role == "CONTROL"
