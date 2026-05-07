"""Tests for ProteinQuantCalibrationPoint model."""
import pytest
from django.core.exceptions import ValidationError

from gel_analyzer.models import Band, Lane, ProteinQuantCalibrationPoint

pytestmark = pytest.mark.django_db


# Aliases for plan-referenced fixtures (the project uses gel_analysis / band).
@pytest.fixture
def sample_analysis(gel_analysis):
    return gel_analysis


@pytest.fixture
def sample_band(band):
    return band


@pytest.fixture
def calibration_lane(sample_analysis, test_user):
    return Lane.objects.create(
        analysis=sample_analysis,
        lane_number=99,
        lane_type=Lane.LaneType.CALIBRATION,
        x=10, y=10, width=50, height=200,
    )


@pytest.fixture
def calibration_band(calibration_lane, test_user):
    return Band.objects.create(
        lane=calibration_lane,
        band_type=Band.BandType.CALIBRATION,
        position_y=100,
        bbox_x=10, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user,
        detection_source=Band.DetectionSource.MANUAL,
    )


class TestProteinQuantCalibrationPoint:
    def test_create_with_valid_data(self, calibration_band):
        point = ProteinQuantCalibrationPoint.objects.create(
            band=calibration_band,
            load_amount=10.0,
            load_unit="UG",
        )
        assert point.role == "CALIBRATION"  # default
        assert point.is_excluded_from_fit is False
        assert point.load_amount == 10.0

    def test_load_amount_rejects_negative(self, calibration_band):
        point = ProteinQuantCalibrationPoint(
            band=calibration_band, load_amount=-1.0, load_unit="UG"
        )
        with pytest.raises(ValidationError):
            point.full_clean()

    def test_one_to_one_with_band(self, calibration_band):
        ProteinQuantCalibrationPoint.objects.create(
            band=calibration_band, load_amount=10.0, load_unit="UG"
        )
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            ProteinQuantCalibrationPoint.objects.create(
                band=calibration_band, load_amount=20.0, load_unit="UG"
            )
