"""Tests for HybridDetectionParams."""

from django.test import TestCase

from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams


class HybridDetectionParamsTest(TestCase):
    """Test sensitivity/toggle mapping to internal params."""

    def test_default_values(self):
        params = HybridDetectionParams()
        self.assertEqual(params.sensitivity, 5)
        self.assertTrue(params.faint_bands)
        self.assertTrue(params.large_bands)

    def test_sensitivity_to_cv2_params_low(self):
        """Sensitivity 1 (conservative) -> high threshold_bias."""
        params = HybridDetectionParams(sensitivity=1)
        cv2_params = params.to_cv2_params()
        self.assertAlmostEqual(cv2_params.threshold_bias, 18.0, places=1)

    def test_sensitivity_to_cv2_params_mid(self):
        params = HybridDetectionParams(sensitivity=5)
        cv2_params = params.to_cv2_params()
        self.assertAlmostEqual(cv2_params.threshold_bias, 10.0, places=1)

    def test_sensitivity_to_cv2_params_high(self):
        params = HybridDetectionParams(sensitivity=10)
        cv2_params = params.to_cv2_params()
        self.assertAlmostEqual(cv2_params.threshold_bias, 4.0, places=1)

    def test_sensitivity_to_derivative_params(self):
        low = HybridDetectionParams(sensitivity=1).to_derivative_params()
        mid = HybridDetectionParams(sensitivity=5).to_derivative_params()
        high = HybridDetectionParams(sensitivity=10).to_derivative_params()
        self.assertAlmostEqual(low.min_snr, 5.0, places=1)
        self.assertAlmostEqual(mid.min_snr, 2.0, places=1)
        # Note: BandDetectionParams.__post_init__ clamps min_snr to >= 0.5
        self.assertAlmostEqual(high.min_snr, 0.5, places=1)

    def test_min_gap_size_mapping(self):
        """Sensitivity maps to min_gap_size_px (floored at 15 = derivative_window)."""
        low = HybridDetectionParams(sensitivity=1)
        mid = HybridDetectionParams(sensitivity=5)
        high = HybridDetectionParams(sensitivity=10)
        self.assertEqual(low.min_gap_size_px, 30)
        self.assertEqual(mid.min_gap_size_px, 20)
        # Sensitivity 10 raw value is 10px, but floored to 15px
        self.assertEqual(high.min_gap_size_px, 15)

    def test_min_gap_size_floor_invariant(self):
        """min_gap_size_px is never below derivative_window default (15)."""
        for s in range(1, 11):
            params = HybridDetectionParams(sensitivity=s)
            self.assertGreaterEqual(
                params.min_gap_size_px, 15, f"sensitivity={s} produced min_gap_size_px={params.min_gap_size_px}"
            )

    def test_faint_band_toggle_on(self):
        on = HybridDetectionParams(faint_bands=True).to_derivative_params()
        off = HybridDetectionParams(faint_bands=False).to_derivative_params()
        self.assertLess(on.threshold_factor, off.threshold_factor)
        self.assertLess(on.d2_significance_factor, off.d2_significance_factor)

    def test_large_band_toggle_on(self):
        on = HybridDetectionParams(large_bands=True).to_cv2_params()
        off = HybridDetectionParams(large_bands=False).to_cv2_params()
        self.assertGreater(on.max_band_area, off.max_band_area)

    def test_sensitivity_clamped(self):
        low = HybridDetectionParams(sensitivity=0)
        high = HybridDetectionParams(sensitivity=15)
        self.assertEqual(low.sensitivity, 1)
        self.assertEqual(high.sensitivity, 10)

    def test_from_dict(self):
        params = HybridDetectionParams.from_dict(
            {
                "sensitivity": 7,
                "faint_bands": False,
                "large_bands": True,
            }
        )
        self.assertEqual(params.sensitivity, 7)
        self.assertFalse(params.faint_bands)
        self.assertTrue(params.large_bands)

    def test_from_dict_empty(self):
        params = HybridDetectionParams.from_dict({})
        self.assertEqual(params.sensitivity, 5)

    def test_to_dict(self):
        params = HybridDetectionParams(sensitivity=7, faint_bands=False)
        d = params.to_dict()
        self.assertEqual(d["sensitivity"], 7)
        self.assertFalse(d["faint_bands"])
        self.assertTrue(d["large_bands"])

    def test_all_toggle_combinations_produce_valid_params(self):
        for faint in (True, False):
            for large in (True, False):
                params = HybridDetectionParams(faint_bands=faint, large_bands=large)
                cv2_p = params.to_cv2_params()
                d1d2_p = params.to_derivative_params()
                self.assertGreater(cv2_p.threshold_bias, 0)
                self.assertGreater(d1d2_p.min_snr, 0)
                self.assertGreater(d1d2_p.derivative_window, 0)

    def test_faint_band_toggle_affects_cv2(self):
        """faint_bands also propagates to CV2 faint_band_boost."""
        on = HybridDetectionParams(faint_bands=True).to_cv2_params()
        off = HybridDetectionParams(faint_bands=False).to_cv2_params()
        self.assertTrue(on.faint_band_boost)
        self.assertFalse(off.faint_band_boost)


def test_new_toggles_default_on():
    params = HybridDetectionParams()
    assert params.split_wide_bands is True
    assert params.mask_loading_wells is True
    assert params.adaptive_threshold is True


def test_to_dict_includes_new_toggles():
    params = HybridDetectionParams(
        sensitivity=7,
        split_wide_bands=False,
        mask_loading_wells=True,
        adaptive_threshold=False,
    )
    d = params.to_dict()
    assert d["split_wide_bands"] is False
    assert d["mask_loading_wells"] is True
    assert d["adaptive_threshold"] is False


def test_from_dict_backward_compat_legacy_dict():
    """Old dicts without the new keys default to True."""
    legacy = {"sensitivity": 5, "faint_bands": True, "large_bands": True}
    params = HybridDetectionParams.from_dict(legacy)
    assert params.split_wide_bands is True
    assert params.mask_loading_wells is True
    assert params.adaptive_threshold is True


def test_from_dict_roundtrip():
    original = HybridDetectionParams(
        sensitivity=3,
        faint_bands=False,
        large_bands=False,
        split_wide_bands=False,
        mask_loading_wells=False,
        adaptive_threshold=False,
    )
    restored = HybridDetectionParams.from_dict(original.to_dict())
    assert restored == original
