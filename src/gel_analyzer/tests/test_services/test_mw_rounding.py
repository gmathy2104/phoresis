"""Verify MW 1-decimal rounding write paths (PR #1 quantification port)."""

import pytest


@pytest.mark.unit
def test_python_round_one_decimal_sanity():
    """Sanity: round(x, 1) behaviour we rely on."""
    assert round(47.83247919, 1) == 47.8
    assert round(0.05, 1) in (0.0, 0.1)  # banker's rounding allowed


@pytest.mark.unit
def test_densito_to_dict_rounds_mw_to_one_decimal():
    """PeakIntegrationResult.to_dict() must serialise MW at 1 decimal precision."""
    from gel_analyzer.services.densitometry.models import PeakIntegrationResult

    p = PeakIntegrationResult(
        band_id="dummy",
        band_type="OTHER",
        position_y=100,
        estimated_mw_kda=47.83247919,
        peak_center=100.0,
        amplitude=1.0,
        sigma=2.0,
        fwhm=4.7,
        integrated_area=100.0,
        background_area=10.0,
        corrected_area=90.0,
        raw_trapezoid_area=90.0,
        fit_r_squared=0.99,
        snr=10.0,
        fit_successful=True,
    )
    out = p.to_dict()
    assert out["estimated_mw_kda"] == 47.8, f"Expected 47.8, got {out['estimated_mw_kda']}"


@pytest.mark.unit
def test_densito_to_dict_handles_none_mw():
    """None MW should pass through unchanged."""
    from gel_analyzer.services.densitometry.models import PeakIntegrationResult

    p = PeakIntegrationResult(
        band_id="dummy",
        band_type="OTHER",
        position_y=100,
        estimated_mw_kda=None,
        peak_center=100.0,
        amplitude=1.0,
        sigma=2.0,
        fwhm=4.7,
        integrated_area=100.0,
        background_area=10.0,
        corrected_area=90.0,
        raw_trapezoid_area=90.0,
        fit_r_squared=0.99,
        snr=10.0,
        fit_successful=True,
    )
    out = p.to_dict()
    assert out["estimated_mw_kda"] is None


@pytest.mark.unit
def test_interpolated_mw_result_to_dict_rounds_to_one_decimal():
    """InterpolatedMWResult.to_dict() must round MW to 1 decimal (calibration path)."""
    from gel_analyzer.services.calibration.models import InterpolatedMWResult

    r = InterpolatedMWResult(estimated_mw_kda=47.83247919, method="LINEAR")
    out = r.to_dict()
    assert out["estimated_mw_kda"] == 47.8, f"Expected 47.8, got {out['estimated_mw_kda']}"
