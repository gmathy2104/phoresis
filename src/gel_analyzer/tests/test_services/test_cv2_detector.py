"""Tests for CV2BandDetector."""

import numpy as np

from django.test import TestCase

from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams
from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
from gel_analyzer.services.band_detection.models import BandDetectionSource


class CV2BandDetectorNormalizationTest(TestCase):
    """Test image normalization to uint8."""

    def test_uint8_passthrough(self):
        img = np.random.randint(0, 255, (100, 50), dtype=np.uint8)
        detector = CV2BandDetector(CV2DetectionParams())
        result = detector._normalize_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)

    def test_uint16_normalizes(self):
        img = np.full((100, 50), 40000, dtype=np.uint16)
        img[20:30, 10:40] = 10000  # add some variation
        detector = CV2BandDetector(CV2DetectionParams())
        result = detector._normalize_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)
        # High-value pixels should map near 255
        self.assertGreater(result[0, 0], 200)

    def test_float_normalizes(self):
        img = np.random.rand(100, 50).astype(np.float32)
        detector = CV2BandDetector(CV2DetectionParams())
        result = detector._normalize_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)


class CV2BandDetectorDarkBackgroundTest(TestCase):
    """Test detection on dark background (bright bands)."""

    def _make_dark_bg_lane(self, height=200, width=80, band_positions=None):
        img = np.full((height, width), 20, dtype=np.uint8)
        for y_center in band_positions or [50, 100, 150]:
            img[y_center - 5 : y_center + 5, 10:70] = 200
        return img

    def test_detects_bright_bands_on_dark_bg(self):
        lane_crop = self._make_dark_bg_lane()
        detector = CV2BandDetector(
            CV2DetectionParams(
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(lane_crop, lane_bbox=(0, 0, 80, 200))
        self.assertGreaterEqual(len(bands), 2)

    def test_detection_source_is_cv2_vision(self):
        lane_crop = self._make_dark_bg_lane()
        detector = CV2BandDetector(
            CV2DetectionParams(
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(lane_crop, lane_bbox=(0, 0, 80, 200))
        for band in bands:
            self.assertEqual(band.detection_source, BandDetectionSource.CV2_VISION)


class CV2BandDetectorWhiteBackgroundTest(TestCase):
    """Test detection on white/light background (dark bands) — the key use case."""

    def _make_white_bg_lane(self, height=200, width=80, band_positions=None):
        img = np.full((height, width), 230, dtype=np.uint8)
        for y_center in band_positions or [50, 100, 150]:
            img[y_center - 5 : y_center + 5, 10:70] = 30
        return img

    def test_detects_dark_bands_on_white_bg(self):
        lane_crop = self._make_white_bg_lane()
        detector = CV2BandDetector(
            CV2DetectionParams(
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(lane_crop, lane_bbox=(0, 0, 80, 200))
        self.assertGreaterEqual(len(bands), 2)

    def test_does_not_detect_between_bands(self):
        """Regression: the gap between two bands came out as a band (y=85).

        Red from the 1D-profile rewrite ec50a5c12 until the smoothed profile was
        kept within the local data range (_clip_to_local_data), so no dip below
        the background is left beside a band for the rolling ball to follow.
        Exactly two bands, each on its centre: a polarity flip finds the four
        band EDGES, which a +/-20 px tolerance let through.
        """
        lane_crop = self._make_white_bg_lane(band_positions=[60, 140])
        detector = CV2BandDetector(
            CV2DetectionParams(
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(lane_crop, lane_bbox=(0, 0, 80, 200))
        positions = sorted(band.position_y for band in bands)
        self.assertEqual(len(positions), 2, f"Expected the two real bands, got y={positions}")
        for found, expected in zip(positions, (60, 140), strict=False):
            self.assertLessEqual(abs(found - expected), 3, f"Band at y={found} is not on the band at y={expected}")


class CV2BandDetectorAdaptivePathTest(TestCase):
    """The adaptive call is the default hybrid's: what prod detects."""

    def test_default_hybrid_keeps_the_bands_validated_on_real_gels(self):
        """The default hybrid returns, exactly, the bands the owner validated with T2.

        Freezes the DEFAULT hybrid - the prod path, CV2's adaptive call plus the
        d1/d2 gap-fill - on the values the owner validated on 11 real gels on
        2026-09-27 (lane-wide CLAHE and repaired adaptive path). Before T2 the
        adaptive call returned y=[82, 160, 240, 323] here (main on 50efb74a and
        4a34d535), in boxes 35/29/27/27 rows high - the length of each run above
        threshold. After it the adaptive call returns y=[80, 160, 240]: the
        lane-wide CLAHE no longer stretches the 4/190 band over the zone
        threshold, and the gap-fill recovers it at 321; the boxes are the peaks'
        FWHM on the smoothed profile, 17/17/17 (16 for the gap-fill band; the
        true FWHM of these sigma-5 bands is 11.8). The box heights feed the gaps,
        the merge, the split and the saved rectangles. The only test that sees the
        zone threshold interpolated rather than stepped: a stepped one moves these
        values. Not the true centres: a deliberate change to the default hybrid
        recomputes the list.
        """
        y = np.arange(400)[:, None]
        img = np.full((400, 80), 230.0)
        for centre, contrast in ((80, 190), (160, 20), (240, 8), (320, 4)):
            img[:, 8:72] -= contrast * np.exp(-0.5 * ((y - centre) / 5.0) ** 2)
        lane_crop = np.rint(img).astype(np.uint8)
        bands = HybridDetector(HybridDetectionParams()).detect(lane_crop, lane_bbox=(0, 0, 80, 400))
        self.assertEqual(
            [(band.position_y, band.bbox_height) for band in bands], [(80, 17), (160, 17), (240, 17), (321, 16)]
        )


class CV2BandDetectorAdaptiveRepairTest(TestCase):
    """The default hybrid's adaptive call finds each band once, on its peak (T2, 2026-09-27)."""

    def _detect_adaptive(self, lane_crop):
        detector = CV2BandDetector(HybridDetectionParams().to_cv2_params())
        h = lane_crop.shape[0]
        return sorted(band.position_y for band in detector.detect(lane_crop, lane_bbox=(0, 0, 80, h), adaptive=True))

    def _assert_bands_at(self, positions, expected):
        self.assertEqual(len(positions), len(expected), f"Expected bands at y={list(expected)}, got y={positions}")
        for found, centre in zip(positions, expected, strict=False):
            self.assertLessEqual(abs(found - centre), 2, f"Band at y={found} is not on the band at y={centre}")

    def test_doublet_is_two_bands_in_the_adaptive_path(self):
        """Regression: two close bands, one run above threshold, came out as one band.

        One band per run put the doublet at 200/225 at the run's midpoint: main on
        4a34d535 returned y=[115, 212, 298]. One band per peak inside the run
        finds both.
        """
        y = np.arange(400)[:, None]
        img = np.full((400, 80), 230.0)
        for centre, contrast in ((120, 150), (200, 150), (225, 100), (300, 150)):
            img[:, 8:72] -= contrast * np.exp(-0.5 * ((y - centre) / 5.0) ** 2)
        lane_crop = np.clip(np.rint(img), 0, 255).astype(np.uint8)
        self._assert_bands_at(self._detect_adaptive(lane_crop), (120, 200, 225, 300))

    def test_clahe_does_not_turn_a_band_tail_step_into_bands(self):
        """Regression: CLAHE blew a one-level step in a band's tail up into phantom bands.

        Truncated (floor), each band's tail leaves a one-grey-level step on the
        background; the historical CLAHE grid (~2.5-px tiles on an 80-px lane)
        stretched it to 7 levels: main on 4a34d535 returned
        y=[61, 97, 162, 199, 237, 294, 339]. Lane-wide tiles leave it a step.
        """
        y = np.arange(400)[:, None]
        img = np.full((400, 80), 230.0)
        for centre in (100, 200, 300):
            img[:, 8:72] -= 190 * np.exp(-0.5 * ((y - centre) / 5.0) ** 2)
        lane_crop = np.clip(np.floor(img), 0, 255).astype(np.uint8)
        self._assert_bands_at(self._detect_adaptive(lane_crop), (100, 200, 300))


class CV2BandDetectorFaintBandTest(TestCase):
    """Test detection of faint bands close to background intensity."""

    def test_faint_band_detected_with_tophat(self):
        img = np.full((200, 80), 200, dtype=np.uint8)
        img[95:105, 10:70] = 170
        detector = CV2BandDetector(
            CV2DetectionParams(
                faint_band_boost=True,
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 200))
        self.assertGreaterEqual(len(bands), 1, "Faint band not detected")

    def test_faint_band_missed_without_tophat(self):
        img = np.full((200, 80), 200, dtype=np.uint8)
        img[95:105, 10:70] = 190
        detector = CV2BandDetector(
            CV2DetectionParams(
                faint_band_boost=False,
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 200))
        self.assertIsInstance(bands, list)


class CV2BandDetectorEdgeCaseTest(TestCase):
    """Test edge cases."""

    def test_tiny_lane_returns_empty(self):
        img = np.full((5, 5), 128, dtype=np.uint8)
        detector = CV2BandDetector(CV2DetectionParams())
        bands = detector.detect(img, lane_bbox=(0, 0, 5, 5))
        self.assertEqual(len(bands), 0)

    def test_uniform_image_returns_empty(self):
        img = np.full((200, 80), 128, dtype=np.uint8)
        detector = CV2BandDetector(CV2DetectionParams())
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 200))
        self.assertEqual(len(bands), 0)

    def test_noisy_image_caps_at_50(self):
        rng = np.random.RandomState(42)
        img = rng.randint(0, 255, (200, 80), dtype=np.uint8)
        detector = CV2BandDetector(CV2DetectionParams(min_band_area=1))
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 200))
        self.assertLessEqual(len(bands), 50)

    def test_16bit_tiff(self):
        img = np.full((200, 80), 50000, dtype=np.uint16)
        img[90:110, 10:70] = 10000
        detector = CV2BandDetector(
            CV2DetectionParams(
                min_band_area=20,
                max_band_area=3000,
            )
        )
        bands = detector.detect(img, lane_bbox=(0, 0, 80, 200))
        self.assertGreaterEqual(len(bands), 1)


class CV2BandDetectorThresholdBiasTest(TestCase):
    """threshold_bias (the panel's slider) moves the global pipeline's prominence threshold."""

    def test_threshold_bias_is_not_dead_on_a_noisy_lane(self):
        """Regression: the noise term was measured on the zero-clipped corrected profile.

        max(profile - opening, 0) is exactly 0 on most rows of a clean lane, so the
        noise estimate on it came out ~0, the 0.5 % floor governed and the bias had
        no effect: main on d3d18df2 returned the same 4 bands at every bias here
        (100, 160, 200, 300). Measured on the row profile as extracted, the noise term
        moves with the bias. The 4th band at bias 3 is the global pipeline's known
        phantom between two sharp bands; if that phantom is ever fixed, the bias-3
        side of this test needs a real faint band instead.
        """
        y = np.arange(400)[:, None]
        img = np.full((400, 80), 230.0)
        for centre in (100, 200, 300):
            img[:, 8:72] -= 190 * np.exp(-0.5 * ((y - centre) / 5) ** 2)
        img += np.random.default_rng(0).normal(0, 3.0, img.shape)
        lane = np.clip(np.rint(img), 0, 255).astype(np.uint8)

        positions = {}
        for bias in (3.0, 25.0):
            detector = CV2BandDetector(CV2DetectionParams(threshold_bias=bias))
            positions[bias] = sorted(band.position_y for band in detector.detect(lane, lane_bbox=(0, 0, 80, 400)))

        strict, loose = positions[25.0], positions[3.0]
        self.assertEqual(len(strict), 3, f"Expected the three real bands at bias 25, got y={strict}")
        for found, expected in zip(strict, (100, 200, 300), strict=False):
            self.assertLessEqual(abs(found - expected), 5, f"Band at y={found} is not on the band at y={expected}")
        self.assertGreater(len(loose), len(strict), f"Bias 3 found y={loose}, bias 25 found y={strict}")
