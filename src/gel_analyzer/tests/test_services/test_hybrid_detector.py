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


def _lane_with_a_band_phase_1_misses():
    """400x80 dark lane, Gaussian bands (sigma 5) of 190/20/8/4 at y=80/160/240/320, pixel noise sigma 3.

    The noise makes the lane gate's noise term, not its 0.5 % floor, set the threshold.
    """
    y = np.arange(400)[:, None]
    img = np.full((400, 80), 25.0)
    for centre, contrast in ((80, 190), (160, 20), (240, 8), (320, 4)):
        img[:, 8:72] += contrast * np.exp(-0.5 * ((y - centre) / 5.0) ** 2)
    img += np.random.default_rng(0).normal(0, 3.0, img.shape)
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


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

        The faintest band (4/190 of the main one, at lane row 320) is under the
        adaptive phase 1 threshold, so only the gap-fill can report it, and it must
        clear the lane noise gate. The lane sits at image y=60, as real lanes do not
        start at 0: the gate reads its profile in lane rows. The fixture this test had
        before (a faint band phase 1 already found) only ever passed on gap-fill bands
        in plain background - the noise the lane gate now drops.
        """
        img = _lane_with_a_band_phase_1_misses()
        detector = HybridDetector(HybridDetectionParams())
        bands = detector.detect(img, lane_bbox=(0, 60, 80, 400))

        phases = [getattr(b, "_hybrid_phase", None) for b in bands]
        self.assertIn("primary", phases)
        gap_fill_ys = [b.position_y for b in bands if getattr(b, "_hybrid_phase", None) == "gap_fill"]
        self.assertTrue(
            any(abs(y - 380) <= 5 for y in gap_fill_ys),
            f"Gap-fill missed the faint band at y=380: gap_fill={gap_fill_ys}, summary={detector.last_summary}",
        )


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


class HybridDetectorNoiseGateTest(TestCase):
    """The bands added after phase 1 (gap-fill, split) must clear the lane-level noise gate."""

    def test_gap_fill_and_split_do_not_report_noise_as_bands(self):
        """Regression: the gap-fill and the split reported the noise between three bands as bands.

        The gap-fill's d1/d2 thresholds are ~1-2 sigma of a noise estimate made on
        each short gap, re-applied on every gap, so a noise excursion nearly always
        passed; the split, cutting at 15 % of a band's own amplitude, cut the noise
        inside a phantom. Main on d3d18df2 added 33 bands here, all in plain background:
        22 from the gap-fill, 11 from the split. Phase 1 bands are outside this test.
        """
        y = np.arange(800)[:, None]
        img = np.full((800, 80), 230.0)
        for centre in (200, 400, 600):
            img[:, 8:72] -= 190 * np.exp(-0.5 * ((y - centre) / 10) ** 2)
        img += np.random.default_rng(0).normal(0, 3.0, img.shape)
        # Floor, not round: the truncation is part of the case.
        lane = np.clip(np.floor(img), 0, 255).astype(np.uint8)

        bands = HybridDetector(HybridDetectionParams()).detect(lane, lane_bbox=(0, 0, 80, 800))

        added = [b.position_y for b in bands if getattr(b, "_hybrid_phase", None) in ("split", "gap_fill")]
        off_band = [y for y in added if min(abs(y - centre) for centre in (200, 400, 600)) > 10]
        self.assertEqual(off_band, [], f"Bands added after phase 1 in plain background: {off_band}")
        for centre in (200, 400, 600):
            self.assertTrue(
                any(abs(b.position_y - centre) <= 10 for b in bands),
                f"The band at y={centre} was lost: y={sorted(b.position_y for b in bands)}",
            )

    def test_gap_fill_band_passes_the_gate_on_a_light_background(self):
        """On a light background (Coomassie) the bands are dips: the gate must flip the profile.

        The faintest band (4/190, at y=640) is under the adaptive phase 1 threshold, so
        only the gap-fill reports it, and it must clear the gate; nothing the gap-fill or
        the split adds may sit in plain background. Without the flip the gate looks for
        maxima where the bands are dips and drops the real band. Phase 1 bands are
        outside this test.
        """
        y = np.arange(800)[:, None]
        img = np.full((800, 80), 230.0)
        for centre, contrast in ((160, 190), (320, 20), (480, 8), (640, 4)):
            img[:, 8:72] -= contrast * np.exp(-0.5 * ((y - centre) / 10.0) ** 2)
        img += np.random.default_rng(0).normal(0, 3.0, img.shape)
        lane = np.clip(np.rint(img), 0, 255).astype(np.uint8)

        bands = HybridDetector(HybridDetectionParams()).detect(lane, lane_bbox=(0, 0, 80, 800))

        gap_fill_ys = [b.position_y for b in bands if getattr(b, "_hybrid_phase", None) == "gap_fill"]
        self.assertTrue(any(abs(y - 640) <= 10 for y in gap_fill_ys), f"Gap-fill missed y=640: {gap_fill_ys}")
        added = [b.position_y for b in bands if getattr(b, "_hybrid_phase", None) in ("split", "gap_fill")]
        off_band = [y for y in added if min(abs(y - centre) for centre in (160, 320, 480, 640)) > 10]
        self.assertEqual(off_band, [], f"Bands added after phase 1 in plain background: {off_band}")
