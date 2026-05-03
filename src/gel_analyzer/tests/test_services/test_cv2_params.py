"""Tests for CV2DetectionParams dataclass."""

import numpy as np

from django.test import TestCase

from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams


class CV2DetectionParamsTest(TestCase):
    """Test CV2DetectionParams creation, validation, serialization."""

    def test_defaults(self):
        p = CV2DetectionParams()
        self.assertEqual(p.block_size, 35)
        self.assertEqual(p.threshold_bias, 10.0)
        self.assertEqual(p.morph_kernel, 3)
        self.assertEqual(p.min_band_area, 50)
        self.assertEqual(p.max_band_area, 5000)
        self.assertTrue(p.faint_band_boost)
        self.assertEqual(p.tophat_radius, 25)
        self.assertTrue(p.clahe_enabled)

    def test_block_size_must_be_odd(self):
        p = CV2DetectionParams(block_size=34)
        self.assertEqual(p.block_size, 35)  # auto-corrected

    def test_block_size_minimum(self):
        p = CV2DetectionParams(block_size=1)
        self.assertEqual(p.block_size, 3)

    def test_morph_kernel_must_be_odd(self):
        p = CV2DetectionParams(morph_kernel=4)
        self.assertEqual(p.morph_kernel, 5)

    def test_min_area_less_than_max(self):
        with self.assertRaises(ValueError):
            CV2DetectionParams(min_band_area=6000, max_band_area=5000)

    def test_to_dict(self):
        p = CV2DetectionParams()
        d = p.to_dict()
        self.assertIn("block_size", d)
        self.assertIn("threshold_bias", d)
        self.assertEqual(d["block_size"], 35)

    def test_from_dict(self):
        d = {"block_size": 45, "threshold_bias": 15.0}
        p = CV2DetectionParams.from_dict(d)
        self.assertEqual(p.block_size, 45)
        self.assertEqual(p.threshold_bias, 15.0)
        self.assertEqual(p.morph_kernel, 3)

    def test_from_dict_ignores_unknown_keys(self):
        d = {"block_size": 45, "unknown_param": 999}
        p = CV2DetectionParams.from_dict(d)
        self.assertEqual(p.block_size, 45)

    def test_from_dict_none(self):
        p = CV2DetectionParams.from_dict(None)
        self.assertEqual(p.block_size, 35)

    def test_from_dict_empty(self):
        p = CV2DetectionParams.from_dict({})
        self.assertEqual(p.block_size, 35)

    def test_auto_calibrate_8bit(self):
        image = np.random.randint(0, 50, (200, 100), dtype=np.uint8)
        p = CV2DetectionParams.auto_calibrate(image, lane_height=200)
        self.assertIsInstance(p, CV2DetectionParams)
        self.assertGreater(p.block_size, 0)

    def test_auto_calibrate_16bit(self):
        image = np.full((400, 80), 45000, dtype=np.uint16)
        p = CV2DetectionParams.auto_calibrate(image, lane_height=400)
        self.assertIsInstance(p, CV2DetectionParams)

    def test_auto_calibrate_scales_with_lane_height(self):
        image = np.random.randint(0, 255, (800, 100), dtype=np.uint8)
        p_small = CV2DetectionParams.auto_calibrate(image, lane_height=200)
        p_large = CV2DetectionParams.auto_calibrate(image, lane_height=800)
        self.assertGreater(p_large.min_band_area, p_small.min_band_area)
