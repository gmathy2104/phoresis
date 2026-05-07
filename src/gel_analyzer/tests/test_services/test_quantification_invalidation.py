"""Tests for the quantification recompute-if-active hook."""
import pytest

from gel_analyzer.models import Band, DensitometryResult, Lane, ProteinQuantCalibration
from gel_analyzer.services.quantification.invalidation import recompute_if_active

pytestmark = pytest.mark.django_db


def test_no_active_calibration_is_noop(sample_analysis):
    # No calibration exists -> must not raise, must return None / 0 sentinel
    assert recompute_if_active(sample_analysis) == 0


def test_active_calibration_refits_and_reapplies(sample_analysis, test_user):
    """Given an active calibration + densitometry data, recompute_if_active should
    write fresh DensitometryResult.estimated_amount values."""
    cal_lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=1, lane_type=Lane.LaneType.CALIBRATION,
        x=0, y=0, width=50, height=200,
    )
    sample_lane = Lane.objects.create(
        analysis=sample_analysis, lane_number=2, lane_type=Lane.LaneType.SAMPLE,
        x=0, y=0, width=50, height=200,
    )
    from gel_analyzer.models import ProteinQuantCalibrationPoint

    # Create ALL bands first — Band.post_save wipes the lane's densitometry,
    # so we must batch densito creation after the last band of each lane.
    cal_specs = [(1000, 5), (2000, 10), (3000, 15)]
    cal_bands = []
    for i, (_area, amount) in enumerate(cal_specs, start=1):
        b = Band.objects.create(
            lane=cal_lane, band_type=Band.BandType.CALIBRATION,
            position_y=i * 50, bbox_x=0, bbox_y=i * 50 - 10,
            bbox_width=50, bbox_height=20,
            created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
        )
        ProteinQuantCalibrationPoint.objects.create(
            band=b, load_amount=amount, load_unit="UG", role="CALIBRATION",
        )
        cal_bands.append(b)
    sample_band = Band.objects.create(
        lane=sample_lane, band_type=Band.BandType.POI,
        position_y=100, bbox_x=0, bbox_y=90, bbox_width=50, bbox_height=20,
        created_by=test_user, detection_source=Band.DetectionSource.MANUAL,
    )

    # Now write densitometry for every band — the lane signal won't fire
    # again because no further Band.save() happens.
    for b, (area, _amount) in zip(cal_bands, cal_specs, strict=False):
        DensitometryResult.objects.create(
            band=b, peak_center_y=b.position_y, peak_amplitude=50, peak_sigma=5,
            fwhm=11.77, integrated_area=area, corrected_area=area,
            fit_r_squared=0.99, snr=20,
        )
    DensitometryResult.objects.create(
        band=sample_band, peak_center_y=100, peak_amplitude=50, peak_sigma=5,
        fwhm=11.77, integrated_area=2500, corrected_area=2500,
        fit_r_squared=0.99, snr=20,
    )
    ProteinQuantCalibration.objects.create(
        analysis=sample_analysis, method="LINEAR", unit="UG",
        coefficients={"a": 0.005, "b": 0.0}, r_squared=1.0, equation="...",
        created_by=test_user,
    )

    n = recompute_if_active(sample_analysis)
    assert n >= 1
    sample_band.densitometry.refresh_from_db()
    assert sample_band.densitometry.estimated_amount == pytest.approx(12.5)
