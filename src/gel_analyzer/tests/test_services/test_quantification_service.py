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

    def test_collects_band_without_densitometry_as_missing(self, sample_analysis, test_user):
        """A calibration band without densitometry must still be COLLECTED (with
        corrected_area=None) so fit() can emit an actionable error rather than
        silently producing a fit with a phantom point set."""
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
        assert points[0].corrected_area is None
        # And confirm fit() rejects the missing-densitometry case with a clear message.
        result = svc.fit(points)
        assert not result.success
        assert "densitometry" in (result.error_message or "").lower()

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


class TestFit:
    def _make_points(self, areas, amounts, role="CALIBRATION"):
        from gel_analyzer.services.quantification.models import QuantPoint
        return [
            QuantPoint(
                band_id=f"b{i}", lane_id=i, lane_number=i, role=role,
                load_amount=a, load_unit="UG", corrected_area=area,
            )
            for i, (area, a) in enumerate(zip(areas, amounts, strict=False), start=1)
        ]

    def test_linear_fit_perfect(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, 3000, 4000], [5, 10, 15, 20])
        result = svc.fit(points)
        assert result.success
        assert result.r_squared == pytest.approx(1.0)
        assert result.coefficients["a"] == pytest.approx(0.005)
        assert result.coefficients["b"] == pytest.approx(0.0)

    def test_excludes_outliers(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, 3000, 9999], [5, 10, 15, 20])
        result = svc.fit(points, excluded_band_ids=["b4"])
        assert result.success
        assert result.r_squared == pytest.approx(1.0)
        assert sum(1 for p in result.calibration_points if p.is_excluded) == 1

    def test_rejects_when_missing_corrected_area(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
        points = self._make_points([1000, 2000, None, 4000], [5, 10, 15, 20])
        result = svc.fit(points)
        assert not result.success
        assert "densitometry" in (result.error_message or "").lower()

    def test_4pl_requires_4_points(self):
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="FOUR_PL", unit="UG"))
        points = self._make_points([1000, 2000, 3000], [5, 10, 15])
        result = svc.fit(points)
        assert not result.success
        assert "4" in (result.error_message or "")

    def test_poly2_fit_happy_path(self):
        """service.fit dispatches POLYNOMIAL_2 correctly: fits, computes equation,
        annotates predicted_amount on every non-excluded point."""
        from gel_analyzer.services.quantification.models import QuantParams
        svc = ProteinQuantCalibrationService(QuantParams(method="POLYNOMIAL_2", unit="UG"))
        # Synthetic dataset that fits a poly2 perfectly: amount = 0.001*area² + 0.5
        points = self._make_points(
            [10, 20, 30, 40, 50],
            [0.6, 0.9, 1.4, 2.1, 3.0],  # 1e-3 * a² + 0.5
        )
        result = svc.fit(points)
        assert result.success
        assert result.method == "POLYNOMIAL_2"
        assert result.r_squared > 0.9999
        assert "coeffs" in result.coefficients
        assert all(p.predicted_amount is not None for p in result.calibration_points if not p.is_excluded)
        assert "area" in result.equation  # formatted via poly2_equation

    def test_4pl_fit_happy_path(self):
        """service.fit dispatches FOUR_PL correctly on a sigmoidal dataset."""
        import numpy as np

        from gel_analyzer.services.quantification.models import QuantParams
        # Build a clean 4PL dataset: amount = d + (a - d) / (1 + (area/c)^b)
        a_, d_, c_, b_ = 0.0, 100.0, 10.0, 1.2
        areas = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
        amounts = [float(d_ + (a_ - d_) / (1 + (np.float64(x) / c_) ** b_)) for x in areas]
        svc = ProteinQuantCalibrationService(QuantParams(method="FOUR_PL", unit="UG"))
        points = self._make_points(areas, amounts)
        result = svc.fit(points)
        assert result.success
        assert result.method == "FOUR_PL"
        assert result.r_squared > 0.999
        assert {"a", "d", "c", "b"} <= set(result.coefficients.keys())
        assert all(p.predicted_amount is not None for p in result.calibration_points if not p.is_excluded)
