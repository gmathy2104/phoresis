"""
Tests for valley-based band boundary detection.

Covers:
- find_valleys() function behavior
- PeakDetector integration with valleys
- BandGeometryBuilder valley-based bbox computation
"""

import numpy as np

from django.test import TestCase

from gel_analyzer.services.band_detection.geometry_builder import BandGeometryBuilder
from gel_analyzer.services.band_detection.models import BandDetectionParams, DetectedPeak, IntensityProfile
from gel_analyzer.services.band_detection.peak_detector import PeakDetector, find_valleys


def _make_synthetic_profile(peaks, length=200, noise=0.0):
    """Create a synthetic 1D profile with Gaussian peaks.

    Args:
        peaks: List of (center, height, sigma) tuples.
        length: Profile length in pixels.
        noise: Additive Gaussian noise stddev.

    Returns:
        1D numpy array.
    """
    x = np.arange(length, dtype=np.float64)
    signal = np.zeros(length, dtype=np.float64)
    for center, height, sigma in peaks:
        signal += height * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    if noise > 0:
        signal += np.random.default_rng(42).normal(0, noise, length)
        signal = np.clip(signal, 0, None)
    return signal


class TestFindValleys(TestCase):
    """Tests for the find_valleys() function."""

    def test_find_valleys_basic(self):
        """Three-peak profile should have 2 valleys between them."""
        data = _make_synthetic_profile(
            [
                (40, 100, 8),
                (100, 80, 8),
                (160, 120, 8),
            ],
            length=200,
        )

        valleys = find_valleys(data, min_distance=10)

        # Filter out boundary indices for the "between peaks" check
        interior_valleys = valleys[(valleys > 20) & (valleys < 180)]
        self.assertGreaterEqual(len(interior_valleys), 2, "Should find at least 2 valleys between 3 peaks")

        # Valleys should be between peaks
        for v in interior_valleys:
            self.assertTrue((30 < v < 80) or (110 < v < 150), f"Valley at {v} not between expected peak ranges")

    def test_find_valleys_includes_boundaries(self):
        """Boundaries 0 and N-1 should always be present."""
        data = _make_synthetic_profile([(50, 100, 10)], length=100)
        valleys = find_valleys(data, min_distance=5)

        self.assertIn(0, valleys, "Should include index 0")
        self.assertIn(99, valleys, "Should include index N-1")

    def test_find_valleys_flat_signal(self):
        """Flat signal should return only boundaries [0, N-1]."""
        data = np.ones(100, dtype=np.float64) * 50.0
        valleys = find_valleys(data, min_distance=5)

        self.assertEqual(list(valleys), [0, 99])

    def test_find_valleys_single_peak(self):
        """Single peak should produce valleys at boundaries only."""
        data = _make_synthetic_profile([(50, 100, 8)], length=100)
        valleys = find_valleys(data, min_distance=5)

        # Must include boundaries
        self.assertIn(0, valleys)
        self.assertIn(99, valleys)


class TestPeakDetectorValleys(TestCase):
    """Tests for PeakDetector populating valley fields."""

    def _run_detector(self, peaks_spec, length=300):
        """Helper: run PeakDetector on a synthetic profile."""
        data = _make_synthetic_profile(peaks_spec, length=length, noise=1.0)
        params = BandDetectionParams(
            sensitivity=0.95,
            peak_distance=10,
            min_band_width_px=3,
            max_band_width_px=100,
            peak_prominence=0.01,
            min_intensity_ratio=1.0,
        )
        profile = IntensityProfile(
            y_positions=list(range(length)),
            raw_intensities=data.tolist(),
            processed_intensities=data.tolist(),
            background=[0.0] * length,
        )
        detector = PeakDetector(params)
        detected = detector.find_peaks(profile)
        return detected, profile

    def test_peak_detector_populates_valley_indices(self):
        """Profile should have valley_indices populated after detection."""
        _, profile = self._run_detector(
            [
                (80, 100, 10),
                (150, 80, 10),
                (220, 120, 10),
            ]
        )
        self.assertTrue(len(profile.valley_indices) > 0, "valley_indices should be populated")
        self.assertIn(0, profile.valley_indices)
        self.assertIn(299, profile.valley_indices)

    def test_detected_peak_valley_fields(self):
        """Each detected peak should have valid left_valley >= 0."""
        peaks, _ = self._run_detector(
            [
                (80, 100, 10),
                (150, 80, 10),
                (220, 120, 10),
            ]
        )
        self.assertGreater(len(peaks), 0, "Should detect at least 1 peak")
        for peak in peaks:
            self.assertGreaterEqual(peak.left_valley, 0, f"Peak at {peak.profile_index}: left_valley should be >= 0")
            self.assertGreaterEqual(peak.right_valley, 0, f"Peak at {peak.profile_index}: right_valley should be >= 0")
            self.assertLess(peak.left_valley, peak.profile_index, "left_valley should be before peak")
            self.assertGreater(peak.right_valley, peak.profile_index, "right_valley should be after peak")


class TestGeometryBuilderValleys(TestCase):
    """Tests for BandGeometryBuilder using valley boundaries."""

    def _make_mock_lane(self, y=0, height=300, x=0, width=50):
        """Create a mock lane object with bbox."""

        class MockLane:
            def __init__(self, bbox_dict):
                self.bbox = bbox_dict

        return MockLane({"x": x, "y": y, "width": width, "height": height})

    def test_geometry_uses_tighter_of_valley_and_prominence(self):
        """When valleys are tighter than prominence, valleys win."""
        params = BandDetectionParams(min_band_width_px=5, max_band_width_px=200)
        builder = BandGeometryBuilder(params)

        y_positions = list(range(300))
        profile = IntensityProfile(
            y_positions=y_positions,
            processed_intensities=[0.0] * 300,
        )
        lane = self._make_mock_lane(y=0, height=300, width=50)

        # Valleys tighter than prominence bases
        peak = DetectedPeak(
            profile_index=150,
            y_position=150,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=100,
            right_base=200,
            left_valley=130,
            right_valley=170,
            snr=5.0,
        )
        bands = builder.build_bands([peak], profile, lane)
        self.assertEqual(bands[0].bbox_y, 130)  # valley (tighter)
        self.assertEqual(bands[0].bbox_height, 40)

    def test_geometry_prominence_wins_for_edge_peaks(self):
        """When valleys extend to profile boundaries, prominence wins."""
        params = BandDetectionParams(min_band_width_px=5, max_band_width_px=200)
        builder = BandGeometryBuilder(params)

        y_positions = list(range(300))
        profile = IntensityProfile(
            y_positions=y_positions,
            processed_intensities=[0.0] * 300,
        )
        lane = self._make_mock_lane(y=0, height=300, width=50)

        # Valleys at profile edges (isolated peak), prominence is tighter
        peak = DetectedPeak(
            profile_index=150,
            y_position=150,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=130,
            right_base=170,
            left_valley=0,
            right_valley=299,
            snr=5.0,
        )
        bands = builder.build_bands([peak], profile, lane)
        self.assertEqual(bands[0].bbox_y, 130)  # prominence (tighter)
        self.assertEqual(bands[0].bbox_height, 40)

    def test_geometry_picks_best_per_side(self):
        """Each side independently picks the tighter boundary."""
        params = BandDetectionParams(min_band_width_px=5, max_band_width_px=200)
        builder = BandGeometryBuilder(params)

        y_positions = list(range(300))
        profile = IntensityProfile(
            y_positions=y_positions,
            processed_intensities=[0.0] * 300,
        )
        lane = self._make_mock_lane(y=0, height=300, width=50)

        # Left: valley tighter (130 vs 100). Right: prominence tighter (170 vs 299).
        peak = DetectedPeak(
            profile_index=150,
            y_position=150,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=100,
            right_base=170,
            left_valley=130,
            right_valley=299,
            snr=5.0,
        )
        bands = builder.build_bands([peak], profile, lane)
        self.assertEqual(bands[0].bbox_y, 130)  # valley (tighter on left)
        self.assertEqual(bands[0].bbox_height, 40)  # 170-130, prominence (tighter on right)

    def test_geometry_fallback_no_valleys(self):
        """With left_valley=-1, should fall back to prominence bases."""
        params = BandDetectionParams(min_band_width_px=5, max_band_width_px=100)
        builder = BandGeometryBuilder(params)

        y_positions = list(range(200))
        profile = IntensityProfile(
            y_positions=y_positions,
            processed_intensities=[0.0] * 200,
        )

        peak = DetectedPeak(
            profile_index=100,
            y_position=100,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=60,
            right_base=140,
            left_valley=-1,
            right_valley=-1,
            snr=5.0,
        )

        lane = self._make_mock_lane(y=0, height=200, width=50)
        bands = builder.build_bands([peak], profile, lane)

        self.assertEqual(len(bands), 1)
        band = bands[0]
        # Prominence-based: bbox_y = y_positions[60] = 60
        self.assertEqual(band.bbox_y, 60)
        self.assertEqual(band.bbox_height, 80)  # 140 - 60

    def test_with_valleys_bbox_not_wider_than_prominence(self):
        """With valleys available, bbox should never be wider than prominence-only."""
        params = BandDetectionParams(min_band_width_px=5, max_band_width_px=150)
        builder = BandGeometryBuilder(params)

        y_positions = list(range(200))
        profile = IntensityProfile(
            y_positions=y_positions,
            processed_intensities=[0.0] * 200,
        )
        lane = self._make_mock_lane(y=0, height=200, width=50)

        # Peak with both valleys and prominence (valleys tighter)
        peak_both = DetectedPeak(
            profile_index=100,
            y_position=100,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=50,
            right_base=150,
            left_valley=85,
            right_valley=115,
            snr=5.0,
        )
        # Same peak but no valleys (falls back to prominence)
        peak_prom = DetectedPeak(
            profile_index=100,
            y_position=100,
            height=50.0,
            prominence=30.0,
            width_px=20,
            left_base=50,
            right_base=150,
            left_valley=-1,
            right_valley=-1,
            snr=5.0,
        )

        bands_both = builder.build_bands([peak_both], profile, lane)
        bands_prom = builder.build_bands([peak_prom], profile, lane)

        self.assertLessEqual(
            bands_both[0].bbox_height,
            bands_prom[0].bbox_height,
            "With valleys, bbox should never be wider than prominence-only",
        )
