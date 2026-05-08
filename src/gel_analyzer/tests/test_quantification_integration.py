"""End-to-end integration test for the protein quantification chain.

Exercises the full path from a multi-lane setup through fit → save → apply →
re-run densitometry → recompute. The unit tests in test_services/ cover their
respective slices; this file guarantees the cross-module contract holds when
all the pieces are wired together for real.

Spec §11 mandates: "4 calibration + 2 control + 3 sample lanes, mocked
densitometry, fit, verify DensitometryResult.estimated_amount propagated;
split a calibration band, verify auto-refit fires through the cache
invalidation path."
"""

import pytest

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    Lane,
    ProteinQuantCalibration,
    ProteinQuantCalibrationPoint,
)
from gel_analyzer.services.quantification.invalidation import recompute_if_active
from gel_analyzer.services.quantification.models import QuantParams
from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

pytestmark = pytest.mark.django_db


def _make_band_with_densito(lane, *, area: float, position_y: int, test_user, band_type=None):
    """Build a Band + its DensitometryResult in one shot.

    Bands first then densitometry rows must be created in two passes when
    multiple bands share a lane — the post_save signal on Band wipes
    DensitometryResult of every sibling. See signals.py for the rationale.
    """
    band = Band.objects.create(
        lane=lane,
        band_type=band_type or Band.BandType.CALIBRATION,
        position_y=position_y,
        bbox_x=0,
        bbox_y=position_y - 10,
        bbox_width=50,
        bbox_height=20,
        created_by=test_user,
        detection_source=Band.DetectionSource.MANUAL,
    )
    return band, area


def _persist_densito(band, area: float):
    return DensitometryResult.objects.create(
        band=band,
        peak_center_y=band.position_y,
        peak_amplitude=50,
        peak_sigma=5,
        fwhm=11.77,
        integrated_area=area,
        corrected_area=area,
        fit_r_squared=0.99,
        snr=20,
    )


def test_full_quantification_chain_4_calib_2_control_3_sample(sample_analysis, test_user):
    """The big-picture integration: 4 calibration + 2 control + 3 sample lanes,
    a saved active calibration, and apply_to_analysis writes estimated_amount
    to every SAMPLE/CONTROL band's DensitometryResult."""
    # Build calibration lanes (load 5 / 10 / 15 / 20 µg, area 1000 / 2000 / 3000 / 4000)
    cal_specs = [(1000, 5), (2000, 10), (3000, 15), (4000, 20)]
    cal_pairs = []  # (band, area)
    for i, (area, amount) in enumerate(cal_specs, start=1):
        lane = Lane.objects.create(
            analysis=sample_analysis,
            lane_number=i,
            lane_type=Lane.LaneType.CALIBRATION,
            x=0,
            y=0,
            width=50,
            height=200,
        )
        band, area = _make_band_with_densito(lane, area=area, position_y=100, test_user=test_user)
        ProteinQuantCalibrationPoint.objects.create(band=band, load_amount=amount, load_unit="UG", role="CALIBRATION")
        cal_pairs.append((band, area))

    # Build 2 CONTROL lanes (loads 10 and 20)
    ctrl_pairs = []
    for i, (area, amount) in enumerate([(2050, 10), (4050, 20)], start=5):
        lane = Lane.objects.create(
            analysis=sample_analysis,
            lane_number=i,
            lane_type=Lane.LaneType.CONTROL,
            x=0,
            y=0,
            width=50,
            height=200,
        )
        band, area = _make_band_with_densito(lane, area=area, position_y=100, test_user=test_user)
        ProteinQuantCalibrationPoint.objects.create(band=band, load_amount=amount, load_unit="UG", role="CONTROL")
        ctrl_pairs.append((band, area))

    # Build 3 SAMPLE lanes with one POI band each (areas 1500 / 2500 / 3500)
    sample_pairs = []
    for i, area in enumerate([1500, 2500, 3500], start=7):
        lane = Lane.objects.create(
            analysis=sample_analysis,
            lane_number=i,
            lane_type=Lane.LaneType.SAMPLE,
            x=0,
            y=0,
            width=50,
            height=200,
        )
        band, area = _make_band_with_densito(
            lane, area=area, position_y=100, test_user=test_user, band_type=Band.BandType.POI
        )
        sample_pairs.append((band, area))

    # All bands created — now persist densitometry (signal won't fire again).
    for band, area in cal_pairs + ctrl_pairs + sample_pairs:
        _persist_densito(band, area)

    # Fit + save + apply
    svc = ProteinQuantCalibrationService(QuantParams(method="LINEAR", unit="UG"))
    points = svc.collect_calibration_points(sample_analysis)
    result = svc.fit(points)
    assert result.success, result.error_message
    assert result.r_squared == pytest.approx(1.0, rel=0.01)
    calib = svc.save_active(sample_analysis, result, user=test_user)
    n_updated = svc.apply_to_analysis(calib)
    # 3 SAMPLE POI bands + 2 CONTROL bands = 5 bands written
    assert n_updated == 5

    # Verify each sample's estimated_amount via the linear fit a=0.005, b=0
    for band, area in sample_pairs:
        band.densitometry.refresh_from_db()
        assert band.densitometry.estimated_amount == pytest.approx(area * 0.005, rel=0.01)
        assert band.densitometry.estimated_amount_unit == "UG"

    # Verify CONTROL recovery: known 10 → predicted ~10.25 (recovery 102%);
    # known 20 → predicted ~20.25 (recovery 101%).
    for band, area in ctrl_pairs:
        band.densitometry.refresh_from_db()
        assert band.densitometry.estimated_amount == pytest.approx(area * 0.005, rel=0.01)


def test_band_split_triggers_recompute_through_invalidation_path(sample_analysis, test_user):
    """Spec §11: split a calibration band, verify auto-refit fires.

    We model "split" as deleting the original band and creating two new ones,
    which is the user-facing operation. The signals on Band.delete + Band.save
    invalidate the lane's densitometry — recompute_if_active is the next
    step in the chain (called at the end of run_densitometry_task in real
    runs; called directly here to model the post-write state).
    """
    cal_lane = Lane.objects.create(
        analysis=sample_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.CALIBRATION,
        x=0,
        y=0,
        width=50,
        height=200,
    )
    sample_lane = Lane.objects.create(
        analysis=sample_analysis,
        lane_number=2,
        lane_type=Lane.LaneType.SAMPLE,
        x=0,
        y=0,
        width=50,
        height=200,
    )

    # Initial fit: 3 calibration bands
    cal_specs = [(1000, 5), (2000, 10), (3000, 15)]
    cal_bands = []
    for i, (_area, amount) in enumerate(cal_specs, start=1):
        band, area = _make_band_with_densito(cal_lane, area=cal_specs[i - 1][0], position_y=i * 50, test_user=test_user)
        ProteinQuantCalibrationPoint.objects.create(band=band, load_amount=amount, load_unit="UG", role="CALIBRATION")
        cal_bands.append(band)
    sample_band = Band.objects.create(
        lane=sample_lane,
        band_type=Band.BandType.POI,
        position_y=100,
        bbox_x=0,
        bbox_y=90,
        bbox_width=50,
        bbox_height=20,
        created_by=test_user,
        detection_source=Band.DetectionSource.MANUAL,
    )
    for b, (area, _amt) in zip(cal_bands, cal_specs, strict=False):
        _persist_densito(b, area)
    _persist_densito(sample_band, 2500)

    active = ProteinQuantCalibration.objects.create(
        analysis=sample_analysis,
        method="LINEAR",
        unit="UG",
        coefficients={"a": 0.005, "b": 0.0},
        r_squared=1.0,
        equation="UG = 0.005·area",
        created_by=test_user,
    )

    # Initial recompute writes estimated_amount = 12.5 (2500 × 0.005)
    n = recompute_if_active(sample_analysis)
    assert n == 1
    sample_band.densitometry.refresh_from_db()
    assert sample_band.densitometry.estimated_amount == pytest.approx(12.5)

    # Now "split" the third calibration band: delete + create two new bands at
    # different positions inside the same lane. The signal handlers on Band
    # post_save / post_delete have already wiped lane densitometry, so we
    # must re-persist the calibration bands' densito rows AND the sample band's
    # densito row before recompute_if_active can run.
    band_to_split = cal_bands[-1]
    band_to_split.delete()
    new_band_a, _ = _make_band_with_densito(cal_lane, area=2900, position_y=150, test_user=test_user)
    new_band_b, _ = _make_band_with_densito(cal_lane, area=3100, position_y=160, test_user=test_user)
    # The remaining first two calibration bands lost their densito to signals;
    # quant_points survived (CASCADE only on band, not on densitometry).
    ProteinQuantCalibrationPoint.objects.create(band=new_band_a, load_amount=14, load_unit="UG", role="CALIBRATION")
    ProteinQuantCalibrationPoint.objects.create(band=new_band_b, load_amount=16, load_unit="UG", role="CALIBRATION")
    # Re-persist densitometry for the calibration lane's bands (this models the
    # densito write-back at the end of run_densitometry_task). The sample lane
    # was never touched by the band-split, so its DensitometryResult survives.
    for b, area in zip(cal_bands[:2], [1000, 2000], strict=False):
        _persist_densito(b, area)
    for b, area in [(new_band_a, 2900), (new_band_b, 3100)]:
        _persist_densito(b, area)

    # The hook fires at the end of densitometry write-back; it must refit on
    # the new 4-point set and reapply.
    n = recompute_if_active(sample_analysis)
    assert n == 1  # one sample band updated

    # The active calibration row has been mutated in place (no new audit row)
    # and last_recomputed_at has ticked.
    active.refresh_from_db()
    assert active.last_recomputed_at is not None
    # Coefficients should still be ~ 0.005 (the split values still lie on a line
    # of slope 5/1000 = 0.005 within rounding); sample stays around 12.5.
    sample_band.densitometry.refresh_from_db()
    assert sample_band.densitometry.estimated_amount == pytest.approx(12.5, rel=0.05)
