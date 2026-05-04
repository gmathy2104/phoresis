"""Tests for HybridDetector."""

import numpy as np

from django.test import TestCase

from gel_analyzer.services.band_detection.hybrid_detector import GapRegion, HybridDetector
from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
from gel_analyzer.services.band_detection.models import BandDetectionSource, DetectedBand


def _make_lane_image(height=400, width=80, band_positions=None, band_intensity=200, bg=20):
    """Create a synthetic gel lane image with bands at specified Y positions."""
    img = np.full((height, width), bg, dtype=np.uint8)
    for y_center in band_positions or []:
        half = 5
        img[max(0, y_center - half) : min(height, y_center + half), 10:70] = band_intensity
    noise = np.random.RandomState(42).randint(0, 15, (height, width), dtype=np.uint8)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


class GapIdentificationTest(TestCase):
    """Test _find_gaps logic."""

    def test_gaps_between_bands(self):
        bands = [
            DetectedBand(position_y=50, bbox_x=0, bbox_y=40, bbox_width=80, bbox_height=20),
            DetectedBand(position_y=150, bbox_x=0, bbox_y=140, bbox_width=80, bbox_height=20),
            DetectedBand(position_y=250, bbox_x=0, bbox_y=240, bbox_width=80, bbox_height=20),
        ]
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        gaps = detector._find_gaps(bands, lane_y=0, lane_height=300)
        self.assertEqual(len(gaps), 4)
        self.assertEqual(gaps[0].start, 0)
        self.assertEqual(gaps[0].end, 40)
        self.assertEqual(gaps[1].start, 60)
        self.assertEqual(gaps[1].end, 140)

    def test_tiny_gap_skipped(self):
        bands = [
            DetectedBand(position_y=50, bbox_x=0, bbox_y=40, bbox_width=80, bbox_height=20),
            DetectedBand(position_y=65, bbox_x=0, bbox_y=60, bbox_width=80, bbox_height=10),
        ]
        params = HybridDetectionParams(sensitivity=1)
        detector = HybridDetector(params)
        gaps = detector._find_gaps(bands, lane_y=0, lane_height=200)
        for gap in gaps:
            self.assertGreaterEqual(gap.end - gap.start, params.min_gap_size_px)

    def test_no_bands_single_gap(self):
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        gaps = detector._find_gaps([], lane_y=0, lane_height=300)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].start, 0)
        self.assertEqual(gaps[0].end, 300)


class HybridDetectorPipelineTest(TestCase):
    def test_cv2_primary_finds_clear_bands(self):
        img = _make_lane_image(band_positions=[80, 200, 320])
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        self.assertGreaterEqual(len(bands), 2)

    def test_all_bands_tagged_hybrid(self):
        img = _make_lane_image(band_positions=[80, 200, 320])
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        for band in bands:
            self.assertEqual(band.detection_source, BandDetectionSource.HYBRID)

    def test_no_overlap_between_bands(self):
        img = _make_lane_image(band_positions=[60, 140, 220, 300])
        params = HybridDetectionParams(sensitivity=7)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        sorted_bands = sorted(bands, key=lambda b: b.bbox_y)
        for i in range(len(sorted_bands) - 1):
            band_bottom = sorted_bands[i].bbox_y + sorted_bands[i].bbox_height
            next_top = sorted_bands[i + 1].bbox_y
            self.assertLessEqual(
                band_bottom, next_top, f"Band {i} bottom ({band_bottom}) overlaps band {i + 1} top ({next_top})"
            )

    def test_bands_sorted_by_y(self):
        img = _make_lane_image(band_positions=[300, 100, 200])
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        positions = [b.position_y for b in bands]
        self.assertEqual(positions, sorted(positions))

    def test_empty_lane_returns_empty(self):
        img = np.full((400, 80), 20, dtype=np.uint8)
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        self.assertEqual(len(bands), 0)

    def test_summary_counts(self):
        img = _make_lane_image(band_positions=[80, 200, 320])
        params = HybridDetectionParams(sensitivity=5)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))
        summary = detector.last_summary
        self.assertIn("primary_bands", summary)
        self.assertIn("gap_fill_bands", summary)
        self.assertEqual(summary["primary_bands"] + summary["gap_fill_bands"], len(bands))

    def test_gap_fill_actually_runs(self):
        """REGRESSION: ensure d1/d2 gap-fill executes — not silently no-op.

        Constructs a lane with two strong bands far apart (CV2 finds them)
        and one faint band in the middle of the gap (CV2 may miss it,
        d1/d2 should catch it). If gap-fill is broken, total bands == 2.
        """
        img = np.full((400, 80), 30, dtype=np.uint8)
        img[40:60, 10:70] = 220
        img[300:320, 10:70] = 220
        img[170:185, 10:70] = 110
        rng = np.random.RandomState(42)
        img = np.clip(img.astype(np.int16) + rng.randint(0, 12, img.shape), 0, 255).astype(np.uint8)

        params = HybridDetectionParams(sensitivity=8, faint_bands=True)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))

        gap_fill_count = detector.last_summary.get("gap_fill_bands", 0)
        self.assertGreater(
            gap_fill_count, 0, f"Gap-fill produced 0 bands. summary={detector.last_summary}, total_bands={len(bands)}"
        )

    def test_gap_fill_bands_tagged_as_gap_fill(self):
        img = np.full((400, 80), 30, dtype=np.uint8)
        img[40:60, 10:70] = 220
        img[300:320, 10:70] = 220
        img[170:185, 10:70] = 110
        rng = np.random.RandomState(42)
        img = np.clip(img.astype(np.int16) + rng.randint(0, 12, img.shape), 0, 255).astype(np.uint8)

        params = HybridDetectionParams(sensitivity=8, faint_bands=True)
        detector = HybridDetector(params)
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 400))

        phases = [getattr(b, "_hybrid_phase", None) for b in bands]
        self.assertIn("primary", phases)
        self.assertIn("gap_fill", phases)


class ClipToGapTest(TestCase):
    def test_clip_shrinks_band(self):
        band = DetectedBand(position_y=100, bbox_x=0, bbox_y=90, bbox_width=80, bbox_height=30)
        gap = GapRegion(start=95, end=115)
        detector = HybridDetector(HybridDetectionParams())
        clipped = detector._clip_to_gap(band, gap)
        self.assertGreaterEqual(clipped.bbox_y, gap.start)
        self.assertLessEqual(clipped.bbox_y + clipped.bbox_height, gap.end)

    def test_clip_discards_tiny_band(self):
        band = DetectedBand(position_y=100, bbox_x=0, bbox_y=98, bbox_width=80, bbox_height=4)
        gap = GapRegion(start=100, end=101)
        detector = HybridDetector(HybridDetectionParams())
        clipped = detector._clip_to_gap(band, gap)
        self.assertIsNone(clipped)
