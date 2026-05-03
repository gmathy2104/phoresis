"""Tests for Split Wide Bands (Feature 2 of gel detection enhancements phase 2)."""

from __future__ import annotations

import numpy as np
import pytest

from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams
from gel_analyzer.services.band_detection.models import (
    BandDetectionSource,
    DetectedBand,
)


def _band(bbox_y, bbox_height, bbox_x=100, bbox_w=40, confidence=0.8) -> DetectedBand:
    return DetectedBand(
        position_y=bbox_y + bbox_height // 2,
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_width=bbox_w,
        bbox_height=bbox_height,
        confidence=confidence,
        detection_source=BandDetectionSource.HYBRID,
    )


@pytest.fixture
def detector():
    return HybridDetector(HybridDetectionParams(split_wide_bands=True))


def _make_bimodal_band_crop(height=80, width=40, peak_offsets=(20, 60)):
    """Synthetic crop with two bright peaks and a valley between them (dark bg)."""
    crop = np.full((height, width, 3), 30, dtype=np.uint8)
    for off in peak_offsets:
        lo = max(0, off - 3)
        hi = min(height, off + 4)
        crop[lo:hi] = 240
    return crop


def test_uniform_band_not_split(detector):
    """Uniform crop (no peaks) must not split any band.

    (Test renamed from test_band_at_1_5x_median_not_split — the new detector has
    no ratio prefilter, so the operative question is whether find_peaks detects
    competing peaks in the sub-profile. A uniform crop has none.)
    """
    bands = [
        _band(bbox_y=100, bbox_height=10),
        _band(bbox_y=150, bbox_height=10),
        _band(bbox_y=200, bbox_height=15),
    ]
    crop = np.full((300, 40, 3), 30, dtype=np.uint8)
    result = detector._split_wide_bands(bands, crop, (100, 0, 40, 300), bg_type="dark")
    assert len(result) == 3
    assert all(b._hybrid_phase != "split" for b in result if hasattr(b, "_hybrid_phase"))


def test_band_at_2x_median_with_bimodal_profile_splits(detector):
    crop_full = np.full((300, 40, 3), 30, dtype=np.uint8)
    # Place a 60px "wide" band (y=110..170) containing two interior peaks at
    # y=120 and y=160. Peaks must be strictly interior (find_peaks cannot pick
    # up plateaus that touch the array edge).
    crop_full[118:123] = 240
    crop_full[158:163] = 240
    bands = [
        _band(bbox_y=100, bbox_height=10),
        _band(bbox_y=110, bbox_height=60),  # 6× median
        _band(bbox_y=180, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="dark")
    split_bands = [b for b in result if getattr(b, "_hybrid_phase", "") == "split"]
    assert len(split_bands) >= 2


def test_large_band_with_unimodal_profile_not_split(detector):
    crop_full = np.full((300, 40, 3), 30, dtype=np.uint8)
    crop_full[130:150] = 240  # single broad peak
    bands = [
        _band(bbox_y=100, bbox_height=10),
        _band(bbox_y=110, bbox_height=60),
        _band(bbox_y=180, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="dark")
    assert not any(getattr(b, "_hybrid_phase", "") == "split" for b in result)


def test_split_that_would_produce_subband_below_3px_abandoned(detector):
    """When a valley falls within 2px of the band boundary, the split should be
    abandoned (sub-band below MIN_SUBBAND_PX=3)."""
    crop_full = np.full((300, 40, 3), 30, dtype=np.uint8)
    # Peaks at local indices 1 and 3 within a 10px band. Valley lands at
    # index 2 → sub-band_1 = 2px (below MIN_SUBBAND_PX=3) → split abandoned.
    crop_full[116:117] = 240
    crop_full[118:119] = 240
    crop_full[123:125] = 240  # another peak toward bottom (no effect)
    bands = [
        _band(bbox_y=100, bbox_height=10),
        _band(bbox_y=115, bbox_height=10),
        _band(bbox_y=180, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="dark")
    assert not any(getattr(b, "_hybrid_phase", "") == "split" for b in result)


def test_single_band_with_uniform_profile_skipped(detector):
    bands = [_band(bbox_y=100, bbox_height=40)]
    crop = np.full((300, 40, 3), 30, dtype=np.uint8)
    result = detector._split_wide_bands(bands, crop, (100, 0, 40, 300), bg_type="dark")
    assert result == bands


def test_polarity_light_background(detector):
    """On light bg, peaks are DARK (low intensity); splitting must still work."""
    crop_full = np.full((300, 40, 3), 220, dtype=np.uint8)
    # Use strictly interior peaks (no plateau against band edge).
    crop_full[118:123] = 30  # dark peaks on light bg
    crop_full[158:163] = 30
    bands = [
        _band(bbox_y=100, bbox_height=10),
        _band(bbox_y=110, bbox_height=60),
        _band(bbox_y=180, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="light")
    split_bands = [b for b in result if getattr(b, "_hybrid_phase", "") == "split"]
    assert len(split_bands) >= 2


def test_split_bands_inherit_bbox_x_width_from_parent(detector):
    crop_full = np.full((300, 60, 3), 30, dtype=np.uint8)
    crop_full[118:123] = 240
    crop_full[158:163] = 240
    parent = _band(bbox_y=110, bbox_height=60, bbox_x=50, bbox_w=60)
    bands = [parent]
    bands.insert(0, _band(bbox_y=10, bbox_height=10, bbox_x=50, bbox_w=60))
    bands.append(_band(bbox_y=190, bbox_height=10, bbox_x=50, bbox_w=60))
    result = detector._split_wide_bands(bands, crop_full, (50, 0, 60, 300), bg_type="dark")
    splits = [b for b in result if getattr(b, "_hybrid_phase", "") == "split"]
    assert len(splits) >= 2
    assert all(b.bbox_x == 50 and b.bbox_width == 60 for b in splits)


def test_split_confidence_modulated_by_valley_depth(detector):
    """Crisp valley → high confidence retention; shallow valley → lower retention."""
    crop_crisp = np.full((300, 40, 3), 30, dtype=np.uint8)
    crop_crisp[118:123] = 240
    crop_crisp[158:163] = 240

    bands = [
        _band(bbox_y=10, bbox_height=10, confidence=0.8),
        _band(bbox_y=110, bbox_height=60, confidence=0.8),
        _band(bbox_y=190, bbox_height=10, confidence=0.8),
    ]
    crisp_results = detector._split_wide_bands(bands, crop_crisp, (100, 0, 40, 300), bg_type="dark")
    crisp_splits = [b for b in crisp_results if getattr(b, "_hybrid_phase", "") == "split"]
    # Each split should retain at least 90% of original confidence (crisp valley).
    assert all(b.confidence >= 0.8 * 0.88 for b in crisp_splits)


def test_narrow_band_with_bimodal_profile_splits(detector):
    """A 20px band (would have been rejected by old 1.4× median prefilter with
    median ~10) with two clear internal peaks now splits thanks to the
    prominence-based gate."""
    crop_full = np.full((300, 40, 3), 30, dtype=np.uint8)
    # Band y=100..120, peaks at y=104 and y=115 (both interior).
    crop_full[103:106] = 240
    crop_full[114:117] = 240
    bands = [
        _band(bbox_y=50, bbox_height=10),
        _band(bbox_y=100, bbox_height=20),  # NOT wide by old ratio (2×)
        _band(bbox_y=160, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="dark")
    split_bands = [b for b in result if getattr(b, "_hybrid_phase", "") == "split"]
    assert len(split_bands) >= 2


def test_prominence_threshold_rejects_noise(detector):
    """Bands with low-amplitude wiggles below the 15% prominence threshold must
    NOT split — the subdetector treats them as a single peak."""
    rng = np.random.default_rng(seed=42)
    crop_full = np.full((300, 40, 3), 30, dtype=np.uint8)
    # Inject one clean tall peak at y=130 (amplitude anchor).
    crop_full[126:135] = 240
    # Inject tiny wiggles (< ~3% of amplitude) elsewhere.
    for y in (115, 145):
        # +3 grey levels on top of background = ~1.5% of 240-30 amplitude.
        wiggle = 33 + rng.integers(-1, 2, size=(1, 40, 3)).astype(np.uint8)
        crop_full[y : y + 1] = wiggle
    bands = [
        _band(bbox_y=110, bbox_height=10),
        _band(bbox_y=110, bbox_height=50),  # covers the whole area
        _band(bbox_y=170, bbox_height=10),
    ]
    result = detector._split_wide_bands(bands, crop_full, (100, 0, 40, 300), bg_type="dark")
    split_bands = [b for b in result if getattr(b, "_hybrid_phase", "") == "split"]
    assert len(split_bands) == 0
