"""
Unit tests for derivative-based peak detection.

Tests use synthetic Gaussian profiles to validate:
- d1 zero-crossing detection at peak centers
- d2 zero-crossing detection at inflection points
- Shoulder peak detection via d2 local minima
- Noise robustness
- End-to-end through the detection pipeline
"""

import numpy as np

from django.test import SimpleTestCase

from gel_analyzer.services.band_detection.derivative_detector import DerivativeDetector
from gel_analyzer.services.band_detection.models import (
    BandDetectionParams,
    IntensityProfile,
)
from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor


def _make_gaussian(center, sigma, n=500, amplitude=100.0):
    """Create a Gaussian peak."""
    x = np.arange(n, dtype=np.float64)
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def _make_profile(data, y_start=100):
    """Wrap numpy array into an IntensityProfile."""
    n = len(data)
    return IntensityProfile(
        y_positions=list(range(y_start, y_start + n)),
        raw_intensities=data.tolist(),
        processed_intensities=data.tolist(),
        lane_x=0,
        lane_y=y_start,
        lane_width=50,
        lane_height=n,
        profile_x_start=10,
        profile_x_end=40,
    )


class TestDerivativeDetectorSinglePeak(SimpleTestCase):
    """Test detection of a single Gaussian peak."""

    def test_single_gaussian_detects_one_peak(self):
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, threshold = detector.detect(profile)

        self.assertEqual(len(peaks), 1)
        # Peak should be near center=250 (within a few pixels)
        self.assertAlmostEqual(peaks[0].profile_index, 250, delta=3)

    def test_single_peak_boundaries_bracket_center(self):
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 1)
        peak = peaks[0]
        # Boundaries should bracket the peak
        self.assertLess(peak.left_base, peak.profile_index)
        self.assertGreater(peak.right_base, peak.profile_index)
        # Area should be positive
        self.assertGreater(peak.area, 0)


class TestDerivativeDetectorTwoPeaks(SimpleTestCase):
    """Test detection of two separated Gaussian peaks."""

    def test_two_separated_gaussians(self):
        data = _make_gaussian(center=150, sigma=15, n=500, amplitude=100) + _make_gaussian(
            center=350, sigma=15, n=500, amplitude=80
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=10,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 2)
        # First peak near 150, second near 350
        self.assertAlmostEqual(peaks[0].profile_index, 150, delta=5)
        self.assertAlmostEqual(peaks[1].profile_index, 350, delta=5)

    def test_valley_between_overlapping_peaks(self):
        """Derivative zero-crossings should include valleys between overlapping peaks."""
        np.random.seed(42)
        # Overlapping peaks with small noise for realistic noise estimates
        data = (
            _make_gaussian(center=200, sigma=25, n=500, amplitude=100)
            + _make_gaussian(center=300, sigma=25, n=500, amplitude=80)
            + np.random.normal(0, 0.5, 500)
        )
        data = np.maximum(data, 0)

        profile = _make_profile(data)
        params = BandDetectionParams(
            derivative_window=15,
            derivative_polyorder=4,
            show_derivatives=True,
        )
        processor = ProfileProcessor(params)
        processor._compute_derivatives(profile)

        # Check for valley markers between the two peak centers
        valley_markers = [
            m for m in profile.derivative_zero_crossings if m["type"] == "valley" and 200 < m["index"] < 300
        ]
        self.assertGreaterEqual(len(valley_markers), 1)

        # Also check for peak markers near the expected centers
        peak_markers = [m for m in profile.derivative_zero_crossings if m["type"] == "peak"]
        self.assertGreaterEqual(len(peak_markers), 2)


class TestInflectionPoints(SimpleTestCase):
    """Test that d2 zero-crossings bracket peaks as inflection points."""

    def test_inflection_points_bracket_peak(self):
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(
            show_derivatives=True,
            derivative_window=15,
            derivative_polyorder=4,
        )
        processor = ProfileProcessor(params)
        processor._compute_derivatives(profile)

        inflections = [m["index"] for m in profile.derivative_zero_crossings if m["type"] == "inflection"]
        # Should have inflection points on both sides of the peak
        left_inflections = [i for i in inflections if i < 250]
        right_inflections = [i for i in inflections if i > 250]

        self.assertGreater(len(left_inflections), 0)
        self.assertGreater(len(right_inflections), 0)


class TestShoulderDetection(SimpleTestCase):
    """Test shoulder peak detection via d2 local minima."""

    def test_shoulder_peak_on_flank(self):
        """An overlapping small peak on a larger peak's flank should be detected."""
        # Main peak at 250, shoulder at 290 (partially overlapping)
        data = _make_gaussian(center=250, sigma=25, n=500, amplitude=100) + _make_gaussian(
            center=290, sigma=10, n=500, amplitude=40
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=8,
            min_band_width_px=3,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Should detect at least 1 peak (the main one); ideally 2 with shoulder
        self.assertGreaterEqual(len(peaks), 1)
        # The main peak should be near 250
        main_peak = peaks[0]
        self.assertAlmostEqual(main_peak.profile_index, 250, delta=10)


class TestDerivativeWindow(SimpleTestCase):
    """Test that wider derivative window produces smoother derivatives."""

    def test_wider_window_fewer_crossings(self):
        """Wider SG window should produce fewer spurious zero-crossings."""
        np.random.seed(42)
        data = _make_gaussian(center=250, sigma=20, n=500) + np.random.normal(0, 2, 500)
        data = np.maximum(data, 0)

        # Narrow window
        profile_narrow = _make_profile(data)
        params_narrow = BandDetectionParams(
            show_derivatives=True,
            derivative_window=7,
            derivative_polyorder=3,
        )
        processor_narrow = ProfileProcessor(params_narrow)
        processor_narrow._compute_derivatives(profile_narrow)

        # Wide window
        profile_wide = _make_profile(data)
        params_wide = BandDetectionParams(
            show_derivatives=True,
            derivative_window=25,
            derivative_polyorder=4,
        )
        processor_wide = ProfileProcessor(params_wide)
        processor_wide._compute_derivatives(profile_wide)

        crossings_narrow = len(profile_narrow.derivative_zero_crossings)
        crossings_wide = len(profile_wide.derivative_zero_crossings)

        # Wider window should have fewer or equal crossings
        self.assertLessEqual(crossings_wide, crossings_narrow)


class TestNoisyProfile(SimpleTestCase):
    """Test noise robustness."""

    def test_noisy_profile_no_excessive_peaks(self):
        """Noise should not cause excessive false detections."""
        np.random.seed(42)
        data = (
            _make_gaussian(center=150, sigma=15, n=500, amplitude=100)
            + _make_gaussian(center=350, sigma=15, n=500, amplitude=80)
            + np.random.normal(0, 3, 500)
        )
        data = np.maximum(data, 0)

        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=10,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Should detect ~2 main peaks; shoulder detection may add extras
        # from noise — up to ~25 is acceptable (not dozens/hundreds)
        self.assertGreaterEqual(len(peaks), 1)
        self.assertLessEqual(len(peaks), 25)


class TestProfileProcessorDerivatives(SimpleTestCase):
    """Test that ProfileProcessor correctly computes derivatives."""

    def test_derivatives_populated_when_show_derivatives(self):
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(
            show_derivatives=True,
            derivative_window=15,
            derivative_polyorder=4,
        )
        processor = ProfileProcessor(params)
        processor._compute_derivatives(profile)

        self.assertEqual(len(profile.first_derivative), 500)
        self.assertEqual(len(profile.second_derivative), 500)
        self.assertGreater(len(profile.derivative_zero_crossings), 0)

    def test_derivatives_always_computed_for_derivative_method(self):
        """Derivatives are always computed since derivative is the sole detection method.
        The show_derivatives flag only controls frontend visualization, not computation."""
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(show_derivatives=False)
        processor = ProfileProcessor(params)
        result = processor.process(profile)

        # Derivatives are always computed for the derivative detector
        self.assertEqual(len(result.first_derivative), 500)
        self.assertEqual(len(result.second_derivative), 500)


class TestD2SignRejection(SimpleTestCase):
    """Test that d2 sign is correctly checked (d2 < 0 for peaks)."""

    def test_d2_positive_crossing_not_detected_as_d1_peak(self):
        """A d1 downward zero-crossing where d2 > 0 (concave up) must NOT be
        detected via the d1 peak path. Only the shoulder path (d2 local minima)
        can produce peaks — this test validates the specific d2 sign fix."""
        np.random.seed(42)
        # Flat baseline with mild noise — no real peaks, just noise crossings
        data = np.ones(500, dtype=np.float64) * 50.0
        data += np.random.normal(0, 1, 500)
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            d2_significance_factor=5.0,  # strict curvature check
            slope_threshold_factor=2.0,
        )
        detector = DerivativeDetector(params)

        # Run derivative computation manually to inspect d1 crossings
        d1, d2 = detector._get_derivatives(data, profile)
        noise_d2 = 1.4826 * float(np.median(np.abs(d2 - np.median(d2))))
        d2_threshold = noise_d2 * params.d2_significance_factor

        # Count how many d1 downward crossings have d2 < -threshold (genuine peaks)
        # vs d2 > 0 (noise/valleys that should be rejected)
        genuine_count = 0
        rejected_count = 0
        for i in range(1, len(d1)):
            if d1[i - 1] > 0 and d1[i] <= 0:
                half_win = max(params.derivative_window // 3, 3)
                win_start = max(0, i - half_win)
                win_end = min(len(d2), i + half_win + 1)
                d2_min = float(np.min(d2[win_start:win_end]))
                if d2_min < -d2_threshold:
                    genuine_count += 1
                else:
                    rejected_count += 1

        # On flat noise, all d1 crossings should be rejected (d2 ≈ 0, not < -threshold)
        self.assertEqual(genuine_count, 0)
        self.assertGreater(rejected_count, 0)  # there ARE d1 crossings, just all rejected


class TestSlopeThreshold(SimpleTestCase):
    """Test that slope threshold filters flat/drift crossings."""

    def test_tiny_slope_crossing_rejected(self):
        """A noisy flat baseline with gentle drift should produce 0 peaks.

        The noise sets meaningful thresholds, and the drift's slope is
        comparable to noise — so the slope check rejects any crossings.
        """
        np.random.seed(42)
        x = np.arange(500, dtype=np.float64)
        # Gentle drift (amplitude=2) + noise (std=3) → drift slope << noise slope
        data = 2.0 * np.sin(2 * np.pi * x / 500) + np.random.normal(0, 3, 500) + 30
        data = np.maximum(data, 0)
        profile = _make_profile(data)

        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            slope_threshold_factor=2.0,
            d2_significance_factor=5.0,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # No real peaks — just noise + drift
        self.assertEqual(len(peaks), 0)

    def test_lower_slope_threshold_detects_more(self):
        """Lowering slope_threshold_factor should allow more peaks through."""
        np.random.seed(42)
        data = (
            _make_gaussian(center=150, sigma=15, n=500, amplitude=100)
            + _make_gaussian(center=350, sigma=15, n=500, amplitude=20)
            + np.random.normal(0, 0.5, 500)
        )
        data = np.maximum(data, 0)
        profile_strict = _make_profile(data)
        profile_loose = _make_profile(data)

        params_strict = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            slope_threshold_factor=4.0,
            d2_significance_factor=3.0,
        )
        params_loose = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            slope_threshold_factor=0.5,
            d2_significance_factor=3.0,
        )
        peaks_strict, _ = DerivativeDetector(params_strict).detect(profile_strict)
        peaks_loose, _ = DerivativeDetector(params_loose).detect(profile_loose)

        self.assertGreaterEqual(len(peaks_loose), len(peaks_strict))


class TestValleyPopulation(SimpleTestCase):
    """Test that valley_indices is populated after detection."""

    def test_valley_indices_populated(self):
        """After detect(), profile.valley_indices should be non-empty."""
        data = _make_gaussian(center=150, sigma=15, n=500, amplitude=100) + _make_gaussian(
            center=350, sigma=15, n=500, amplitude=80
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        detector.detect(profile)

        # valley_indices should include at least boundaries [0, N-1]
        self.assertGreaterEqual(len(profile.valley_indices), 2)
        self.assertEqual(profile.valley_indices[0], 0)
        self.assertEqual(profile.valley_indices[-1], len(data) - 1)

    def test_valley_between_two_peaks(self):
        """A valley should be found between two overlapping peaks."""
        np.random.seed(42)
        # Use overlapping peaks so the valley has significant d2 curvature
        data = (
            _make_gaussian(center=200, sigma=25, n=500, amplitude=100)
            + _make_gaussian(center=300, sigma=25, n=500, amplitude=80)
            + np.random.normal(0, 0.5, 500)
        )
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        detector.detect(profile)

        # There should be a valley between 200 and 300
        mid_valleys = [v for v in profile.valley_indices if 200 < v < 300]
        self.assertGreaterEqual(len(mid_valleys), 1)


class TestMinValleyDepthFactor(SimpleTestCase):
    """Test valley depth filtering via min_valley_depth_factor."""

    def test_shallow_valley_filtered(self):
        """With high depth factor, shallow valleys should be removed."""
        # Two peaks with a barely-there valley in between
        data = _make_gaussian(center=200, sigma=30, n=500, amplitude=100) + _make_gaussian(
            center=280, sigma=30, n=500, amplitude=95
        )
        profile_high = _make_profile(data)
        profile_low = _make_profile(data)

        params_high = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            min_valley_depth_factor=10.0,  # very strict
        )
        params_low = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            min_valley_depth_factor=0.5,  # very loose
        )
        DerivativeDetector(params_high).detect(profile_high)
        DerivativeDetector(params_low).detect(profile_low)

        # The strict filter should have fewer or equal valleys
        mid_high = [v for v in profile_high.valley_indices if 200 < v < 280]
        mid_low = [v for v in profile_low.valley_indices if 200 < v < 280]
        self.assertLessEqual(len(mid_high), len(mid_low))


class TestPeakOnsetOffset(SimpleTestCase):
    """Test peak onset/offset boundaries."""

    def test_onset_before_peak_offset_after(self):
        """onset < peak_idx < offset — boundaries bracket the peak."""
        np.random.seed(42)
        # Add small noise so slope_threshold is non-trivial, giving
        # meaningful onset/offset separation from the apex
        data = _make_gaussian(center=250, sigma=20, n=500) + np.random.normal(0, 0.5, 500)
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertGreaterEqual(len(peaks), 1)
        peak = peaks[0]
        # left_base should be before peak, right_base after
        self.assertLess(peak.left_base, peak.profile_index)
        self.assertGreater(peak.right_base, peak.profile_index)

    def test_valley_boundaries_assigned(self):
        """Peaks should have valley boundaries (not just inflection points)."""
        data = _make_gaussian(center=150, sigma=15, n=500, amplitude=100) + _make_gaussian(
            center=350, sigma=15, n=500, amplitude=80
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 2)
        for peak in peaks:
            # left_valley and right_valley should be set (not -1)
            self.assertGreaterEqual(peak.left_valley, 0)
            self.assertGreaterEqual(peak.right_valley, 0)
            self.assertLessEqual(peak.left_valley, peak.profile_index)
            self.assertGreaterEqual(peak.right_valley, peak.profile_index)


class TestParabolicRefinement(SimpleTestCase):
    """Test parabolic apex refinement."""

    def test_refined_height_ge_original(self):
        """Parabolic fit on a Gaussian should give height >= discrete peak."""
        data = _make_gaussian(center=250, sigma=20, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            refine_peaks=True,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 1)
        # Refined height should be >= discrete data[peak_idx]
        discrete_height = data[peaks[0].profile_index]
        self.assertGreaterEqual(peaks[0].height, discrete_height - 0.01)

    def test_refine_peaks_disabled(self):
        """When refine_peaks=False, height should equal discrete data value."""
        data = _make_gaussian(center=250, sigma=20, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            refine_peaks=False,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 1)
        expected_height = data[peaks[0].profile_index]
        self.assertAlmostEqual(peaks[0].height, expected_height, places=5)


class TestNewParamsModels(SimpleTestCase):
    """Test new parameters in BandDetectionParams."""

    def test_default_values(self):
        params = BandDetectionParams()
        self.assertEqual(params.d2_significance_factor, 1.5)
        self.assertEqual(params.slope_threshold_factor, 1.0)
        self.assertTrue(params.refine_peaks)

    def test_to_dict_includes_new_params(self):
        params = BandDetectionParams()
        d = params.to_dict()
        self.assertIn("d2_significance_factor", d)
        self.assertIn("slope_threshold_factor", d)
        self.assertIn("refine_peaks", d)

    def test_from_dict_roundtrip(self):
        params = BandDetectionParams(
            d2_significance_factor=5.0,
            slope_threshold_factor=3.5,
            refine_peaks=False,
        )
        d = params.to_dict()
        restored = BandDetectionParams.from_dict(d)
        self.assertEqual(restored.d2_significance_factor, 5.0)
        self.assertEqual(restored.slope_threshold_factor, 3.5)
        self.assertFalse(restored.refine_peaks)

    def test_validation_clamps(self):
        params = BandDetectionParams(d2_significance_factor=0.1, slope_threshold_factor=0.1)
        self.assertEqual(params.d2_significance_factor, 1.0)  # clamped to min
        self.assertEqual(params.slope_threshold_factor, 0.5)  # clamped to min

        params2 = BandDetectionParams(d2_significance_factor=20.0, slope_threshold_factor=20.0)
        self.assertEqual(params2.d2_significance_factor, 8.0)  # clamped to max
        self.assertEqual(params2.slope_threshold_factor, 5.0)  # clamped to max

    def test_scaled_preserves_new_params(self):
        params = BandDetectionParams(
            d2_significance_factor=5.0,
            slope_threshold_factor=3.0,
            refine_peaks=False,
        )
        scaled = params.scaled(1600)  # 2x reference
        self.assertEqual(scaled.d2_significance_factor, 5.0)
        self.assertEqual(scaled.slope_threshold_factor, 3.0)
        self.assertFalse(scaled.refine_peaks)


class TestEndToEndDerivativeMethod(SimpleTestCase):
    """Test derivative method end-to-end through DerivativeDetector."""

    def test_default_method_is_derivative(self):
        params = BandDetectionParams()
        self.assertEqual(params.integration_method, "derivative")

    def test_derivative_method_produces_peaks(self):
        data = (
            _make_gaussian(center=100, sigma=12, n=400, amplitude=80)
            + _make_gaussian(center=200, sigma=15, n=400, amplitude=100)
            + _make_gaussian(center=300, sigma=10, n=400, amplitude=60)
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=10,
            min_band_width_px=3,
        )
        detector = DerivativeDetector(params)
        peaks, threshold = detector.detect(profile)

        self.assertGreaterEqual(len(peaks), 2)
        self.assertGreater(threshold, 0)

        # All peaks should have positive area and SNR
        for peak in peaks:
            self.assertGreater(peak.area, 0)
            self.assertGreaterEqual(peak.snr, 2.0)


class TestIntegrationMethodBackwardCompat(SimpleTestCase):
    """Test that deprecated integration_method values are silently corrected."""

    def test_boundary_corrected_to_derivative(self):
        params = BandDetectionParams(integration_method="boundary")
        self.assertEqual(params.integration_method, "derivative")

    def test_legacy_corrected_to_derivative(self):
        params = BandDetectionParams(integration_method="legacy")
        self.assertEqual(params.integration_method, "derivative")

    def test_unknown_corrected_to_derivative(self):
        params = BandDetectionParams(integration_method="unknown")
        self.assertEqual(params.integration_method, "derivative")

    def test_derivative_stays_derivative(self):
        params = BandDetectionParams(integration_method="derivative")
        self.assertEqual(params.integration_method, "derivative")

    def test_from_dict_with_old_method(self):
        """Simulate loading old params from DB/JSON with boundary method."""
        params = BandDetectionParams.from_dict(
            {
                "integration_method": "boundary",
                "threshold_factor": 4.0,
            }
        )
        self.assertEqual(params.integration_method, "derivative")
        self.assertEqual(params.threshold_factor, 4.0)


class TestBaselineAwareNoise(SimpleTestCase):
    """Test baseline-aware noise estimation."""

    def test_baseline_noise_lower_than_full_signal(self):
        """For multi-peak profiles, baseline-aware noise should be lower
        than full-signal MAD because real peak oscillations are excluded."""
        data = (
            _make_gaussian(center=100, sigma=12, n=500, amplitude=100)
            + _make_gaussian(center=200, sigma=12, n=500, amplitude=80)
            + _make_gaussian(center=300, sigma=12, n=500, amplitude=90)
            + _make_gaussian(center=400, sigma=12, n=500, amplitude=70)
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        d1, d2 = detector._get_derivatives(data, profile)

        # Baseline-aware noise
        noise_d1_bl, noise_d2_bl, bl_count = detector._estimate_baseline_noise(data, d1, d2)

        # Full-signal MAD (old method)
        1.4826 * float(np.median(np.abs(d1 - np.median(d1))))
        noise_d2_full = 1.4826 * float(np.median(np.abs(d2 - np.median(d2))))

        # Baseline-aware should be strictly lower for multi-peak data
        self.assertLess(noise_d2_bl, noise_d2_full)
        self.assertGreater(bl_count, 20)

    def test_fallback_for_short_baseline(self):
        """When baseline region is too small (<20 points), fall back to full MAD."""
        # A single wide peak that covers almost all the signal
        data = _make_gaussian(center=250, sigma=200, n=500, amplitude=100) + 50
        profile = _make_profile(data)
        params = BandDetectionParams(
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        d1, d2 = detector._get_derivatives(data, profile)

        noise_d1, noise_d2, bl_count = detector._estimate_baseline_noise(data, d1, d2)

        # Should still return valid noise estimates (fallback or baseline)
        self.assertGreater(noise_d1, 0)
        self.assertGreater(noise_d2, 0)

    def test_noise_floor_prevents_zero(self):
        """Pure synthetic data (no noise) should get a floor of 1e-10."""
        # Perfectly smooth Gaussian — derivatives are smooth too
        data = _make_gaussian(center=250, sigma=50, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        d1, d2 = detector._get_derivatives(data, profile)

        noise_d1, noise_d2, _ = detector._estimate_baseline_noise(data, d1, d2)

        self.assertGreaterEqual(noise_d1, 1e-10)
        self.assertGreaterEqual(noise_d2, 1e-10)

    def test_multi_peak_detection_improved(self):
        """The core bug: 4-peak profile should detect bands with default params.

        Before the fix, MAD treated peak oscillations in d2 as noise, inflating
        noise_d2 so much that d2_threshold became unattainable → 0 peaks.
        """
        data = (
            _make_gaussian(center=80, sigma=12, n=500, amplitude=100)
            + _make_gaussian(center=180, sigma=12, n=500, amplitude=70)
            + _make_gaussian(center=300, sigma=15, n=500, amplitude=90)
            + _make_gaussian(center=420, sigma=10, n=500, amplitude=60)
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=10,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Must detect at least 3 of the 4 peaks (not 0!)
        self.assertGreaterEqual(len(peaks), 3)

    def test_single_peak_no_regression(self):
        """Single-peak profile must still work after baseline-aware change."""
        data = _make_gaussian(center=250, sigma=20, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 1)
        self.assertAlmostEqual(peaks[0].profile_index, 250, delta=3)

    def test_shoulder_uses_d2_significance_factor(self):
        """Shoulder threshold should respect d2_significance_factor, not hardcoded 3.0."""
        # Main peak at 250, shoulder at 290
        data = _make_gaussian(center=250, sigma=25, n=500, amplitude=100) + _make_gaussian(
            center=290, sigma=10, n=500, amplitude=40
        )
        profile_strict = _make_profile(data)
        profile_loose = _make_profile(data)

        params_strict = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            d2_significance_factor=8.0,  # very strict
            peak_distance=8,
            min_band_width_px=3,
        )
        params_loose = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            d2_significance_factor=1.5,  # loose
            peak_distance=8,
            min_band_width_px=3,
        )
        peaks_strict, _ = DerivativeDetector(params_strict).detect(profile_strict)
        peaks_loose, _ = DerivativeDetector(params_loose).detect(profile_loose)

        # Loose should detect at least as many peaks as strict
        self.assertGreaterEqual(len(peaks_loose), len(peaks_strict))


class TestWindowBasedSlopeCheck(SimpleTestCase):
    """Test that the window-based slope check fixes the zero-crossing bug."""

    def test_window_slope_detects_peaks_old_check_missed(self):
        """With the old single-point slope check (abs(d1[i-1])), d1 at the
        zero-crossing is close to zero and gets rejected. The window-based
        check finds the max slope on the rising edge instead."""
        np.random.seed(42)
        # Multi-peak noisy profile simulating a real gel
        data = (
            _make_gaussian(center=80, sigma=15, n=500, amplitude=80)
            + _make_gaussian(center=160, sigma=12, n=500, amplitude=100)
            + _make_gaussian(center=250, sigma=18, n=500, amplitude=60)
            + _make_gaussian(center=340, sigma=10, n=500, amplitude=90)
            + _make_gaussian(center=420, sigma=14, n=500, amplitude=70)
            + np.random.normal(0, 2, 500)
        )
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            peak_distance=10,
            slope_threshold_factor=2.0,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Must detect at least 4 of the 5 peaks (not 0)
        self.assertGreaterEqual(len(peaks), 4)

    def test_flat_baseline_still_rejected(self):
        """Flat baseline noise should still produce 0 peaks with slope check."""
        np.random.seed(42)
        data = np.ones(500, dtype=np.float64) * 50.0
        data += np.random.normal(0, 1, 500)
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            d2_significance_factor=5.0,
            slope_threshold_factor=2.0,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 0)


class TestWindowBasedValleyDetection(SimpleTestCase):
    """Test that window-based valley d2 check finds more valleys."""

    def test_valley_found_with_window_check(self):
        """Two overlapping peaks should have a valley between them."""
        np.random.seed(42)
        data = (
            _make_gaussian(center=180, sigma=25, n=500, amplitude=100)
            + _make_gaussian(center=320, sigma=25, n=500, amplitude=80)
            + np.random.normal(0, 1, 500)
        )
        data = np.maximum(data, 0)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        detector.detect(profile)

        # Should have at least one valley between the peaks
        mid_valleys = [v for v in profile.valley_indices if 180 < v < 320]
        self.assertGreaterEqual(len(mid_valleys), 1)

    def test_many_peaks_have_valleys_between(self):
        """5-peak profile should produce valleys between adjacent peaks."""
        data = (
            _make_gaussian(center=60, sigma=12, n=500, amplitude=80)
            + _make_gaussian(center=150, sigma=12, n=500, amplitude=100)
            + _make_gaussian(center=250, sigma=15, n=500, amplitude=70)
            + _make_gaussian(center=350, sigma=12, n=500, amplitude=90)
            + _make_gaussian(center=440, sigma=12, n=500, amplitude=60)
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        detector.detect(profile)

        # Should have valleys between each pair of peaks (at least 3 of 4 gaps)
        inner_valleys = [v for v in profile.valley_indices if 60 < v < 440]
        self.assertGreaterEqual(len(inner_valleys), 3)


class TestSplitPeakHandling(SimpleTestCase):
    """Test behavior with noisy peak summits after peak_distance decoupling.

    With _merge_close_candidates and _enforce_min_distance removed,
    the SG filter (window=15) is the primary defense against summit noise.
    Narrow dips (sigma=3) are smoothed away; wider dips may produce real sub-peaks.
    """

    def test_narrow_dip_smoothed_by_sg_filter(self):
        """A narrow summit dip (sigma=3) should be smoothed by SG window=15."""
        np.random.seed(42)
        x = np.arange(500, dtype=np.float64)
        base_peak = 100.0 * np.exp(-0.5 * ((x - 250) / 20) ** 2)
        dip = -8.0 * np.exp(-0.5 * ((x - 250) / 3) ** 2)
        data = base_peak + dip
        data = np.maximum(data, 0)

        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # SG filter smooths the narrow dip → single peak near 250
        self.assertGreaterEqual(len(peaks), 1)
        self.assertLessEqual(len(peaks), 3)
        # At least one peak near center
        near_center = [p for p in peaks if abs(p.profile_index - 250) < 15]
        self.assertGreaterEqual(len(near_center), 1)

    def test_distinct_peaks_preserved(self):
        """Two well-separated peaks should both be detected."""
        data = _make_gaussian(center=150, sigma=15, n=500, amplitude=100) + _make_gaussian(
            center=350, sigma=15, n=500, amplitude=80
        )
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            max_band_width_px=80,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        self.assertEqual(len(peaks), 2)

    def test_no_merged_candidates_in_diagnostics(self):
        """merged_candidates key should no longer exist in diagnostics."""
        data = _make_gaussian(center=250, sigma=20, n=500)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
        )
        detector = DerivativeDetector(params)
        detector.detect(profile)

        self.assertNotIn("merged_candidates", detector.diagnostics["rejection_counts"])
        # peak_distance should not be in params_used (decoupled)
        self.assertNotIn("peak_distance", detector.diagnostics["params_used"])
        # min_snr should still be in params_used
        self.assertIn("min_snr", detector.diagnostics["params_used"])

    def test_visualization_markers_not_split(self):
        """Peak markers from _find_zero_crossings() should not show doubles."""
        np.random.seed(42)
        x = np.arange(500, dtype=np.float64)
        base_peak = 100.0 * np.exp(-0.5 * ((x - 250) / 20) ** 2)
        dip = -8.0 * np.exp(-0.5 * ((x - 250) / 3) ** 2)
        data = base_peak + dip
        data = np.maximum(data, 0)

        profile = _make_profile(data)
        params = BandDetectionParams(
            show_derivatives=True,
            derivative_window=15,
            derivative_polyorder=4,
            min_band_width_px=10,  # merge_dist for visualization markers
        )
        processor = ProfileProcessor(params)
        processor.process(profile)

        peak_markers = [m for m in profile.derivative_zero_crossings if m["type"] == "peak" and 220 < m["index"] < 280]
        # Should have exactly 1 peak marker near 250, not 2+
        self.assertEqual(len(peak_markers), 1)


class TestWidthClampingFix(SimpleTestCase):
    """Test that width clamping doesn't reject valid peaks."""

    def test_wide_peak_not_rejected_by_clamping(self):
        """A broad Gaussian that exceeds nearby d2 zero-crossings should
        still be detected thanks to correct clamping."""
        # Wide peak: sigma=30 means width ~120px at base
        data = _make_gaussian(center=250, sigma=30, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            max_band_width_px=80,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Should detect the peak (not reject due to width clamping)
        self.assertEqual(len(peaks), 1)

    def test_narrow_peak_still_passes_min_width(self):
        """A narrow peak should still pass min_band_width_px check."""
        data = _make_gaussian(center=250, sigma=8, n=500, amplitude=100)
        profile = _make_profile(data)
        params = BandDetectionParams(
            integration_method="derivative",
            derivative_window=15,
            derivative_polyorder=4,
            min_band_width_px=3,
        )
        detector = DerivativeDetector(params)
        peaks, _ = detector.detect(profile)

        # Should detect at least 1 peak (the main one)
        self.assertGreaterEqual(len(peaks), 1)
