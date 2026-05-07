"""
Tests for densitometry peak integration after the bbox-truncation fix.

Covers the two scientific guarantees the bbox-truncated integrator must hold,
and the regression case (single peak split in two halves) that motivated the
fix.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gel_analyzer.services.densitometry.models import DensitometryParams
from gel_analyzer.services.densitometry.peak_integrator import (
    PeakIntegrator,
    gaussian_truncated_area,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Pure function: gaussian_truncated_area
# ---------------------------------------------------------------------------


class TestGaussianTruncatedArea:
    """``gaussian_truncated_area`` is the closed form integral the fitter uses."""

    def test_full_window_recovers_analytic_total(self):
        """A wide-enough window should reproduce the standard ``A·σ·√(2π)``."""
        amplitude, center, sigma = 10.0, 50.0, 5.0
        # 10σ each side = effectively −∞..+∞ for a Gaussian
        area = gaussian_truncated_area(amplitude, center, sigma, center - 10 * sigma, center + 10 * sigma)
        expected = amplitude * sigma * math.sqrt(2 * math.pi)
        assert area == pytest.approx(expected, rel=1e-6)

    def test_split_at_center_returns_half_total(self):
        """Splitting the window at the peak center should give half the total."""
        amplitude, center, sigma = 10.0, 50.0, 5.0
        full = amplitude * sigma * math.sqrt(2 * math.pi)
        upper_half = gaussian_truncated_area(amplitude, center, sigma, center - 10 * sigma, center)
        lower_half = gaussian_truncated_area(amplitude, center, sigma, center, center + 10 * sigma)
        assert upper_half == pytest.approx(full / 2, rel=1e-6)
        assert lower_half == pytest.approx(full / 2, rel=1e-6)

    def test_split_partition_sums_to_total(self):
        """For ANY split point, sum of the two pieces must equal the full area.

        This is the property that fixes the band-split-doubles-the-area bug.
        """
        amplitude, center, sigma = 10.0, 50.0, 5.0
        full = gaussian_truncated_area(amplitude, center, sigma, center - 10 * sigma, center + 10 * sigma)

        for split in (45.0, 48.0, 50.0, 52.0, 55.0):
            upper = gaussian_truncated_area(amplitude, center, sigma, center - 10 * sigma, split)
            lower = gaussian_truncated_area(amplitude, center, sigma, split, center + 10 * sigma)
            assert upper + lower == pytest.approx(full, rel=1e-6), f"split={split}"

    def test_window_outside_peak_is_near_zero(self):
        """Far from the peak, area is ≈ 0."""
        area = gaussian_truncated_area(amplitude=10.0, center=50.0, sigma=2.0, lower=80.0, upper=90.0)
        assert area == pytest.approx(0.0, abs=1e-6)

    def test_degenerate_inputs_return_zero(self):
        """Sigma ≤ 0 or upper ≤ lower must not raise — return 0 instead."""
        assert gaussian_truncated_area(10.0, 50.0, 0.0, 40.0, 60.0) == 0.0
        assert gaussian_truncated_area(10.0, 50.0, -1.0, 40.0, 60.0) == 0.0
        assert gaussian_truncated_area(10.0, 50.0, 5.0, 60.0, 60.0) == 0.0
        assert gaussian_truncated_area(10.0, 50.0, 5.0, 60.0, 40.0) == 0.0


# ---------------------------------------------------------------------------
# Integration test: split a real peak in halves
# ---------------------------------------------------------------------------


def _gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
    return amplitude * np.exp(-((x - center) ** 2) / (2 * sigma**2))


class _StubProfile:
    """Minimal stand-in for ``IntensityProfile`` consumed by ``PeakIntegrator.integrate_band``."""

    def __init__(self, y_positions, intensities):
        self.y_positions = list(y_positions)
        self.processed_intensities = list(intensities)
        self.is_empty = len(intensities) == 0


class _StubBand:
    """Minimal stand-in for the ``Band`` model — duck-typed via ``.bbox``."""

    def __init__(self, band_id: str, position_y: int, bbox_y: int, bbox_height: int):
        self.id = band_id
        self.band_type = "OTHER"
        self.position_y = position_y
        self.estimated_mw_kda = None
        self._bbox_y = bbox_y
        self._bbox_height = bbox_height

    @property
    def bbox(self):
        return {"x": 0, "y": self._bbox_y, "width": 50, "height": self._bbox_height}


class TestSplitPreservesArea:
    """Splitting one band in two halves must preserve the total integrated area.

    Regression test for the ``A·σ·√(2π)`` extrapolation bug — see
    ``peak_integrator.gaussian_truncated_area`` docstring.
    """

    def _make_lane_profile(self):
        """A lane with a single Gaussian peak centered at y=100, σ=5."""
        y = np.arange(0, 200, dtype=float)
        intensities = _gaussian(y, amplitude=100.0, center=100.0, sigma=5.0)
        return _StubProfile(y.tolist(), intensities.tolist())

    def test_full_band_around_peak(self):
        """A bbox containing the whole peak gives ≈ ``A·σ·√(2π)``."""
        profile = self._make_lane_profile()
        band = _StubBand("full", position_y=100, bbox_y=80, bbox_height=40)

        params = DensitometryParams(profile_already_corrected=True)
        integrator = PeakIntegrator(params)
        result = integrator.integrate_band(band, profile)

        expected = 100.0 * 5.0 * math.sqrt(2 * math.pi)
        assert result.fit_successful
        # 2% tolerance accounts for sample-grid quantization vs analytic integral
        assert result.corrected_area == pytest.approx(expected, rel=0.02)

    def test_split_at_peak_does_not_double_area(self):
        """Two half-bboxes must sum to the original full-bbox area, not double it."""
        profile = self._make_lane_profile()

        params = DensitometryParams(profile_already_corrected=True)
        integrator = PeakIntegrator(params)

        full_band = _StubBand("full", position_y=100, bbox_y=80, bbox_height=40)
        full_area = integrator.integrate_band(full_band, profile).corrected_area

        # Split at y=100 (peak center). Each half-bbox is 20 px tall.
        upper_band = _StubBand("upper", position_y=90, bbox_y=80, bbox_height=20)
        lower_band = _StubBand("lower", position_y=110, bbox_y=100, bbox_height=20)

        upper_area = integrator.integrate_band(upper_band, profile).corrected_area
        lower_area = integrator.integrate_band(lower_band, profile).corrected_area

        # Σ(halves) ≈ full, well within 5% — would be ≈ 2× full under the
        # old ``A·σ·√(2π)`` extrapolation.
        assert upper_area + lower_area == pytest.approx(full_area, rel=0.05)
        # Sanity: each half is roughly half the total
        assert upper_area == pytest.approx(full_area / 2, rel=0.10)
        assert lower_area == pytest.approx(full_area / 2, rel=0.10)

    def test_peak_center_stays_inside_bbox(self):
        """The fitted ``peak_center`` must not leak outside the user's bbox."""
        profile = self._make_lane_profile()
        # Bbox catches only the rising edge of the peak — the peak max sits
        # at y=100, but the bbox stops at y=98.
        band = _StubBand("rising-edge", position_y=92, bbox_y=85, bbox_height=13)

        params = DensitometryParams(profile_already_corrected=True)
        integrator = PeakIntegrator(params)
        result = integrator.integrate_band(band, profile)

        if result.fit_successful:
            # Whatever the fit converges to, the chromatogram marker must
            # land inside the bbox the user drew, otherwise the densitometry
            # view diverges from the annotation electropherogram.
            assert 85 <= result.peak_center <= 98
