"""Tests for Loading Well Masking (Feature 3 of gel detection enhancements phase 2)."""

from __future__ import annotations

import numpy as np
import pytest

from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams

TOP_REGION_FRACTION = 0.12
VARIANCE_RATIO_THRESHOLD = 0.6
MAX_MASK_FRACTION = 0.15


def _make_lane_crop(lane_h=400, lane_w=40, noise_top_rows=0, peak_at=None, bg="dark"):
    """Build a synthetic lane crop.

    bg='dark': background is black (low intensity), bands are bright.
    bg='light': background is white (high intensity), bands are dark.
    """
    base = 30 if bg == "dark" else 220
    crop = np.full((lane_h, lane_w, 3), base, dtype=np.uint8)

    if bg == "dark":
        noise_val = 180
        peak_val = 240
    else:
        noise_val = 90
        peak_val = 40

    # Chaotic noise in top region (loading well simulation)
    rng = np.random.default_rng(42)
    if noise_top_rows > 0:
        if bg == "light":
            # Light bg: noise dips DOWN from `base` toward `noise_val`.
            low, high = noise_val, base - 20
        else:
            # Dark bg: noise spikes UP from `base` toward `noise_val`.
            low, high = base, noise_val
        crop[:noise_top_rows] = rng.integers(
            low=low,
            high=high,
            size=(noise_top_rows, lane_w, 3),
            dtype=np.uint8,
        )

    # Optional clear peak somewhere
    if peak_at is not None:
        crop[peak_at - 3 : peak_at + 3] = peak_val

    return crop


@pytest.fixture
def detector():
    return HybridDetector(HybridDetectionParams(mask_loading_wells=True))


def test_mask_applied_when_top_is_noisy_no_peak(detector):
    crop = _make_lane_crop(lane_h=400, noise_top_rows=48, peak_at=None)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    # Mask should start somewhere >= initial 12% = 48px
    assert effective_bbox[1] >= 48
    assert effective_bbox[3] <= 400 - 48


def test_no_mask_when_clear_peak_in_top_region(detector):
    crop = _make_lane_crop(lane_h=400, noise_top_rows=0, peak_at=20)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    assert effective_bbox[1] == 0
    assert effective_bbox[3] == 400


def test_no_mask_when_variance_ratio_below_threshold(detector):
    crop = _make_lane_crop(lane_h=400, noise_top_rows=0)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    # Quiet top → no mask
    assert effective_bbox == bbox


def test_growing_mask_extends_past_12_percent(detector):
    # Noise extends to 25% of lane (well beyond the 12% starting window)
    crop = _make_lane_crop(lane_h=400, noise_top_rows=100, peak_at=None)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    mask_h = effective_bbox[1]
    # Should grow past initial 48px but not past the hard cap (15% = 60px)
    assert 48 <= mask_h <= 60


def test_growing_mask_stops_on_prominent_peak(detector):
    # Noise from 0 to 40px, then a clear peak at 60px
    crop = _make_lane_crop(lane_h=400, noise_top_rows=40, peak_at=60)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    mask_h = effective_bbox[1]
    # Mask should not extend into or past the peak
    assert mask_h < 60


def test_max_mask_fraction_clamp(detector):
    # Entire top 25% is noisy
    crop = _make_lane_crop(lane_h=400, noise_top_rows=100)
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="dark")
    mask_h = effective_bbox[1]
    # Hard clamp at 15% * 400 = 60
    assert mask_h <= 60


def test_polarity_light_background(detector):
    crop = _make_lane_crop(lane_h=400, noise_top_rows=48, bg="light")
    bbox = (100, 0, 40, 400)
    effective_bbox = detector._compute_effective_bbox(crop, bbox, bg_type="light")
    # Should still detect the chaotic top and mask it
    assert effective_bbox[1] >= 48


def test_effective_bbox_propagated_to_cv2(detector, monkeypatch):
    """When mask_loading_wells=True, CV2BandDetector.detect receives effective_lane_bbox, not raw."""
    crop = _make_lane_crop(lane_h=400, noise_top_rows=48)
    bbox = (100, 0, 40, 400)
    received_bbox = {}

    real_cv2 = detector.cv2_detector.detect

    def _spy(lane_crop, lane_bbox, **kwargs):
        received_bbox["bbox"] = lane_bbox
        return real_cv2(lane_crop, lane_bbox, **kwargs)

    monkeypatch.setattr(detector.cv2_detector, "detect", _spy)
    detector.detect(crop, bbox)
    # CV2 should have been called with a bbox whose y is > 0
    assert received_bbox["bbox"][1] > 0
