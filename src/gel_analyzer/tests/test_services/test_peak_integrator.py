# UNPLUGGED: boundary mode tests — derivative detection is the sole automatic method
"""
Tests for the boundary-centric peak integration algorithm.

Tests cover all 4 canonical boundary cases:
1. Baseline-Baseline: Isolated peak, fully resolved
2. Baseline-Valley: First peak in a group of overlapping peaks
3. Valley-Valley: Middle peak between two adjacent peaks
4. Valley-Baseline: Last peak in a group of overlapping peaks
"""

import numpy as np

from django.test import SimpleTestCase

from gel_analyzer.services.band_detection.models import (
    BandDetectionParams,
    IntensityProfile,
)
from gel_analyzer.services.band_detection.peak_integrator import (
    BoundaryType,
    PeakIntegrator,
    integrated_bands_to_peaks,
)


def _make_profile(intensities, y_start=0):
    """Helper to create an IntensityProfile from a list of intensities."""
    n = len(intensities)
    return IntensityProfile(
        y_positions=list(range(y_start, y_start + n)),
        raw_intensities=list(intensities),
        processed_intensities=list(intensities),
        background=[0.0] * n,
        lane_x=0,
        lane_y=y_start,
        lane_width=50,
        lane_height=n,
    )


def _gaussian(x, center, amplitude, sigma):
    """Generate a Gaussian peak."""
    return amplitude * np.exp(-((x - center) ** 2) / (2 * sigma**2))


class TestPeakIntegratorSinglePeak(SimpleTestCase):
    """Test single isolated peak (Baseline-Baseline)."""

    def test_single_gaussian_peak(self):
        """A single Gaussian should produce one band with B-B boundaries."""
        x = np.arange(100)
        data = _gaussian(x, 50, 100, 8)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,  # auto
            threshold_factor=3.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 1)
        band = bands[0]
        self.assertEqual(band.left_boundary.boundary_type, BoundaryType.BASELINE)
        self.assertEqual(band.right_boundary.boundary_type, BoundaryType.BASELINE)
        self.assertAlmostEqual(band.peak_index, 50, delta=2)
        self.assertGreater(band.area, 0)
        self.assertGreater(band.snr, 2.0)
        self.assertGreater(threshold, 0)

    def test_single_peak_manual_threshold(self):
        """Manual threshold should be used when min_peak_height > 0."""
        x = np.arange(100)
        data = _gaussian(x, 50, 100, 8)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=20.0,  # manual
            min_band_width_px=2,
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(threshold, 20.0)
        self.assertEqual(len(bands), 1)


class TestPeakIntegratorTwoOverlapping(SimpleTestCase):
    """Test two overlapping peaks (Baseline-Valley, Valley-Baseline)."""

    def test_two_overlapping_peaks(self):
        """Two partially overlapping Gaussians should produce B-V and V-B."""
        x = np.arange(120)
        data = _gaussian(x, 40, 100, 10) + _gaussian(x, 70, 80, 10)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_valley_depth_factor=1.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 2)

        # First peak: Baseline-Valley
        self.assertEqual(bands[0].left_boundary.boundary_type, BoundaryType.BASELINE)
        self.assertEqual(bands[0].right_boundary.boundary_type, BoundaryType.VALLEY)

        # Second peak: Valley-Baseline
        self.assertEqual(bands[1].left_boundary.boundary_type, BoundaryType.VALLEY)
        self.assertEqual(bands[1].right_boundary.boundary_type, BoundaryType.BASELINE)

        # Peak positions should be near 40 and 70
        self.assertAlmostEqual(bands[0].peak_index, 40, delta=3)
        self.assertAlmostEqual(bands[1].peak_index, 70, delta=3)


class TestPeakIntegratorThreeOverlapping(SimpleTestCase):
    """Test three overlapping peaks (all 4 boundary types)."""

    def test_three_overlapping_peaks(self):
        """Three overlapping peaks: B-V, V-V, V-B."""
        x = np.arange(150)
        data = _gaussian(x, 35, 100, 10) + _gaussian(x, 65, 80, 10) + _gaussian(x, 95, 90, 10)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_valley_depth_factor=1.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 3)

        # First: Baseline-Valley
        self.assertEqual(bands[0].left_boundary.boundary_type, BoundaryType.BASELINE)
        self.assertEqual(bands[0].right_boundary.boundary_type, BoundaryType.VALLEY)

        # Middle: Valley-Valley
        self.assertEqual(bands[1].left_boundary.boundary_type, BoundaryType.VALLEY)
        self.assertEqual(bands[1].right_boundary.boundary_type, BoundaryType.VALLEY)

        # Last: Valley-Baseline
        self.assertEqual(bands[2].left_boundary.boundary_type, BoundaryType.VALLEY)
        self.assertEqual(bands[2].right_boundary.boundary_type, BoundaryType.BASELINE)


class TestThresholdFiltering(SimpleTestCase):
    """Test that peaks below threshold are rejected."""

    def test_peak_below_threshold_rejected(self):
        """A tiny peak below the threshold should not be detected."""
        x = np.arange(100)
        # Small peak with height 5
        data = _gaussian(x, 50, 5, 8)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=10.0,  # threshold above peak
            min_band_width_px=2,
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)
        self.assertEqual(threshold, 10.0)

    def test_mixed_peaks_threshold(self):
        """Only peaks above threshold should be detected."""
        x = np.arange(150)
        # One tall peak (100), one short peak (8)
        data = _gaussian(x, 50, 100, 10) + _gaussian(x, 100, 8, 10)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=15.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 1)
        self.assertAlmostEqual(bands[0].peak_index, 50, delta=3)


class TestAutoThreshold(SimpleTestCase):
    """Test auto-threshold calculation."""

    def test_auto_threshold_scales_with_noise(self):
        """Auto threshold should be proportional to noise level."""
        x = np.arange(200)
        np.random.seed(42)
        # Clean signal with known peak
        data = _gaussian(x, 100, 50, 15) + np.random.normal(0, 1, 200).clip(0)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_band_width_px=2,
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        # Threshold should be relatively small compared to peak
        self.assertGreater(threshold, 0)
        self.assertLess(threshold, 50)  # Should not exceed the peak height
        self.assertGreater(len(bands), 0)

    def test_high_threshold_factor_fewer_bands(self):
        """Higher threshold_factor should detect fewer bands."""
        x = np.arange(200)
        np.random.seed(42)
        noise = np.random.normal(0, 2, 200).clip(0)
        data = _gaussian(x, 60, 50, 10) + _gaussian(x, 130, 15, 10) + noise
        profile_low = _make_profile(data)
        profile_high = _make_profile(data)

        params_low = BandDetectionParams(
            integration_method="boundary",
            threshold_factor=2.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )
        params_high = BandDetectionParams(
            integration_method="boundary",
            threshold_factor=8.0,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=5,
        )

        bands_low, _ = PeakIntegrator(params_low).integrate(profile_low)
        bands_high, _ = PeakIntegrator(params_high).integrate(profile_high)

        self.assertGreaterEqual(len(bands_low), len(bands_high))


class TestValleyDepthFiltering(SimpleTestCase):
    """Test that shallow valleys don't cause splitting."""

    def test_shallow_valley_no_split(self):
        """A very high min_valley_depth_factor should prevent splitting."""
        x = np.arange(120)
        # Two overlapping peaks with a shallow valley between them
        data = _gaussian(x, 40, 100, 12) + _gaussian(x, 70, 80, 12)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_valley_depth_factor=100.0,  # Very high = no valley splitting
            min_band_width_px=2,
            max_band_width_px=200,
            peak_distance=1,
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        # With very high valley depth factor, should see 1 merged band
        self.assertEqual(len(bands), 1)


class TestEdgeCases(SimpleTestCase):
    """Test edge cases."""

    def test_empty_profile(self):
        """Empty profile should return no bands."""
        profile = IntensityProfile()
        params = BandDetectionParams(integration_method="boundary")
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)
        self.assertEqual(threshold, 0.0)

    def test_flat_signal(self):
        """Flat signal should return no bands."""
        data = np.full(100, 5.0)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)

    def test_short_profile(self):
        """Very short profile should return no bands."""
        data = [10.0, 50.0, 10.0]
        profile = _make_profile(data)

        params = BandDetectionParams(integration_method="boundary")
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)

    def test_all_below_threshold(self):
        """When all data is below threshold, no bands."""
        data = np.full(100, 1.0)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=10.0,
        )
        integrator = PeakIntegrator(params)
        bands, threshold = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)


class TestAreaIntegration(SimpleTestCase):
    """Test area integration accuracy."""

    def test_rectangular_peak_area(self):
        """A rectangular peak should have area = height * width."""
        # Create a simple rectangular peak
        data = np.zeros(100)
        data[30:60] = 50.0  # height=50, width=30
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=10.0,
            min_band_width_px=2,
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        self.assertEqual(len(bands), 1)
        # np.trapezoid of a rectangular pulse of height 50, width 30 = 50*29 = 1450
        # (trapz uses N-1 intervals for N points)
        self.assertAlmostEqual(bands[0].area, 50.0 * 29, delta=1.0)


class TestConversionToDetectedPeaks(SimpleTestCase):
    """Test integrated_bands_to_peaks conversion."""

    def test_conversion_preserves_data(self):
        """Conversion should preserve peak position and boundaries."""
        x = np.arange(100)
        data = _gaussian(x, 50, 100, 10)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_band_width_px=2,
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        self.assertGreater(len(bands), 0)

        peaks = integrated_bands_to_peaks(bands, profile)

        self.assertEqual(len(peaks), len(bands))
        peak = peaks[0]
        band = bands[0]

        self.assertEqual(peak.profile_index, band.peak_index)
        self.assertEqual(peak.y_position, profile.y_positions[band.peak_index])
        self.assertAlmostEqual(peak.height, band.peak_height)
        self.assertEqual(peak.left_base, band.left_boundary.index)
        self.assertEqual(peak.right_base, band.right_boundary.index)
        self.assertGreater(peak.area, 0)
        self.assertGreater(peak.snr, 0)


class TestWidthFiltering(SimpleTestCase):
    """Test that width constraints filter correctly."""

    def test_narrow_band_rejected(self):
        """Band narrower than min_band_width_px should be rejected."""
        # Narrow peak: only 3px wide above threshold
        data = np.zeros(100)
        data[49:52] = 50.0
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=10.0,
            min_band_width_px=10,  # min 10px
            max_band_width_px=80,
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)

    def test_wide_band_rejected(self):
        """Band wider than max_band_width_px should be rejected."""
        data = np.zeros(200)
        data[20:180] = 50.0  # 160px wide
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=10.0,
            min_band_width_px=2,
            max_band_width_px=80,  # max 80px
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        self.assertEqual(len(bands), 0)


class TestMinPeakDistance(SimpleTestCase):
    """Test minimum peak distance enforcement."""

    def test_close_peaks_merged(self):
        """Peaks closer than peak_distance should have one removed."""
        x = np.arange(100)
        # Two peaks very close together
        data = _gaussian(x, 48, 80, 5) + _gaussian(x, 55, 100, 5)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="boundary",
            min_peak_height=0,
            threshold_factor=3.0,
            min_valley_depth_factor=0.5,
            min_band_width_px=2,
            max_band_width_px=80,
            peak_distance=15,  # large distance requirement
        )
        integrator = PeakIntegrator(params)
        bands, _ = integrator.integrate(profile)

        # Should keep at most 1 due to distance constraint
        self.assertLessEqual(len(bands), 1)
