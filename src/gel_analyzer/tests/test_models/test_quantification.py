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


class TestProteinQuantCalibration:
    def test_create_active(self, sample_analysis, test_user):
        from gel_analyzer.models import ProteinQuantCalibration
        calib = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis,
            method="LINEAR",
            unit="UG",
            coefficients={"a": 0.0021, "b": 0.43},
            r_squared=0.98,
            equation="y = 0.0021·area + 0.43",
            created_by=test_user,
        )
        assert calib.is_active is True
        assert calib.superseded_at is None

    def test_only_one_active_per_analysis(self, sample_analysis, test_user):
        from gel_analyzer.models import ProteinQuantCalibration
        from django.db import IntegrityError
        ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 1, "b": 0}, r_squared=0.99, equation="y=x",
            created_by=test_user,
        )
        with pytest.raises(IntegrityError):
            ProteinQuantCalibration.objects.create(
                analysis=sample_analysis, method="LINEAR", unit="UG",
                coefficients={"a": 2, "b": 0}, r_squared=0.99, equation="y=2x",
                created_by=test_user, is_active=True,
            )

    def test_superseded_allows_new_active(self, sample_analysis, test_user):
        """When the previous one is marked is_active=False, a new active is allowed."""
        from gel_analyzer.models import ProteinQuantCalibration
        from django.utils import timezone
        old = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 1, "b": 0}, r_squared=0.99, equation="y=x",
            created_by=test_user,
        )
        old.is_active = False
        old.superseded_at = timezone.now()
        old.save()
        new = ProteinQuantCalibration.objects.create(
            analysis=sample_analysis, method="LINEAR", unit="UG",
            coefficients={"a": 2, "b": 0}, r_squared=0.99, equation="y=2x",
            created_by=test_user,
        )
        assert new.is_active is True


class TestDensitometryResultEstimatedAmount:
    def test_fields_default_null(self, sample_band, test_user):
        from gel_analyzer.models import DensitometryResult
        dr = DensitometryResult.objects.create(
            band=sample_band, peak_center_y=100, peak_amplitude=50,
            peak_sigma=5, fwhm=11.77, integrated_area=500,
            corrected_area=500, fit_r_squared=0.99, snr=20,
        )
        assert dr.estimated_amount is None
        assert dr.estimated_amount_unit == ""

    def test_can_persist_estimated_amount(self, sample_band, test_user):
        from gel_analyzer.models import DensitometryResult
        dr = DensitometryResult.objects.create(
            band=sample_band, peak_center_y=100, peak_amplitude=50,
            peak_sigma=5, fwhm=11.77, integrated_area=500,
            corrected_area=500, fit_r_squared=0.99, snr=20,
            estimated_amount=12.3, estimated_amount_unit="UG",
        )
        dr.refresh_from_db()
        assert dr.estimated_amount == 12.3
        assert dr.estimated_amount_unit == "UG"
