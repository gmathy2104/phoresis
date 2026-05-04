"""Tests for the CV2 detector's relative prominence floor."""

import numpy as np

from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams


def _synthetic_profile(dynamic_range: float, n: int = 400) -> np.ndarray:
    """Build a flat-ish profile with a single peak scaled to dynamic_range."""
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.1, size=n)
    profile = noise + 10.0
    peak_height = dynamic_range - 0.5
    for i in range(n):
        profile[i] += peak_height * np.exp(-((i - 200) ** 2) / (2 * 10**2))
    return profile


class TestProminenceFloor:
    """Relative prominence floor scales with signal dynamic range."""

    def test_low_dynamic_range_has_proportionally_low_floor(self):
        """A faint gel (range ~10) should use floor ~0.05, not pinned at 2.0."""
        detector = CV2BandDetector(CV2DetectionParams())
        profile = _synthetic_profile(dynamic_range=10.0)

        bands = detector._find_bands(profile, lane_h=400)

        assert len(bands) >= 1, "Single clear peak on faint gel not detected"

    def test_high_dynamic_range_noise_floor_dominates(self):
        """On a full-scale gel (range ~200) with a conservative threshold bias,
        the noise-relative floor suppresses speckle and keeps only clearly
        prominent peaks.  bias=50 → prominence_factor≈7.5 → floor ≈ 21
        for σ=5 noise, so only the 150-unit genuine band clears the threshold."""
        rng = np.random.default_rng(0)
        n = 400
        profile = rng.normal(0, 5.0, size=n) + 50.0
        profile[200:220] += 150.0  # one tall clean peak

        # Use a conservative threshold_bias to drive prominence_factor high
        # enough that σ=5 random wiggles (~prominence 8-20) are suppressed.
        detector = CV2BandDetector(CV2DetectionParams(threshold_bias=50.0))
        bands = detector._find_bands(profile, lane_h=400)

        # Should detect ~1 peak, not a field of speckle-level peaks.
        assert 1 <= len(bands) <= 3, f"Expected 1-3 bands on noisy profile with one clear peak, got {len(bands)}"
