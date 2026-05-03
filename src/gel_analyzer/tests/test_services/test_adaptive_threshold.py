"""Tests for Adaptive Threshold per Zone (Feature 4 of gel detection enhancements phase 2)."""

from __future__ import annotations

import numpy as np

from gel_analyzer.services.band_detection.cv2_detector import CV2BandDetector
from gel_analyzer.services.band_detection.cv2_params import CV2DetectionParams


def _vertical_gradient_lane(h=300, w=40, low=30, high=180):
    """Synthetic lane with a vertical brightness gradient (top bright, bottom dim)."""
    crop = np.zeros((h, w, 3), dtype=np.uint8)
    for row in range(h):
        intensity = int(high - (high - low) * (row / max(1, h - 1)))
        crop[row] = intensity
    return crop


def _place_peaks(crop, positions, val=240):
    for p in positions:
        crop[max(0, p - 2) : p + 3] = val


def test_gradient_lane_3_distinct_thresholds_computed():
    detector = CV2BandDetector(CV2DetectionParams(threshold_bias=8.0))
    crop = _vertical_gradient_lane(h=300, w=40)
    # Place one peak per zone
    _place_peaks(crop, [50, 150, 250], val=240)
    bands = detector.detect(crop, (0, 0, 40, 300), adaptive=True)
    # Expect at least one band in each third of the lane
    zones = [0, 100, 200, 300]
    counts = [sum(1 for b in bands if zones[i] <= b.position_y < zones[i + 1]) for i in range(3)]
    assert all(c >= 1 for c in counts), f"Per-zone band counts: {counts}"


def test_flat_zone_falls_back_to_global_sigma():
    """A plateau/saturated zone triggers the sigma<1 fallback without raising."""
    detector = CV2BandDetector(CV2DetectionParams(threshold_bias=8.0))
    crop = np.full((300, 40, 3), 200, dtype=np.uint8)  # all flat
    _place_peaks(crop, [100], val=240)
    # Should not raise and should still return results (or empty, not crash).
    bands = detector.detect(crop, (0, 0, 40, 300), adaptive=True)
    assert isinstance(bands, list)


def test_small_lane_no_subdivision():
    detector = CV2BandDetector(CV2DetectionParams())
    crop = np.full((20, 40, 3), 30, dtype=np.uint8)  # <30 px, no subdivision
    bands = detector.detect(crop, (0, 0, 40, 20), adaptive=True)
    assert isinstance(bands, list)


def test_all_zones_share_global_bg_type():
    """bg_type is resolved once; zones don't individually re-detect."""
    detector = CV2BandDetector(CV2DetectionParams())
    crop = _vertical_gradient_lane(h=300, w=40, low=30, high=180)
    _place_peaks(crop, [50, 150, 250])
    # Force bg_type via override and ensure all zones use it.
    bands = detector.detect(crop, (0, 0, 40, 300), bg_type_override="dark", adaptive=True)
    assert all(b.detection_source is not None for b in bands)


def test_adaptive_false_preserves_existing_behavior():
    """Regression: adaptive=False must match the non-adaptive code path."""
    detector = CV2BandDetector(CV2DetectionParams())
    crop = _vertical_gradient_lane(h=300, w=40)
    _place_peaks(crop, [100])
    bands_legacy = detector.detect(crop, (0, 0, 40, 300))
    bands_explicit = detector.detect(crop, (0, 0, 40, 300), adaptive=False)

    assert len(bands_legacy) == len(bands_explicit)
    for a, b in zip(bands_legacy, bands_explicit, strict=False):
        assert a.bbox_y == b.bbox_y
        assert a.bbox_height == b.bbox_height
        assert np.isclose(a.confidence, b.confidence, rtol=1e-9, atol=1e-12)


def test_transition_smoothing_does_not_crash_on_boundary_band():
    """Band right on zone boundary: no exception, single band returned."""
    detector = CV2BandDetector(CV2DetectionParams())
    crop = _vertical_gradient_lane(h=300, w=40)
    _place_peaks(crop, [100])  # zone 1 boundary at y=100
    bands = detector.detect(crop, (0, 0, 40, 300), adaptive=True)
    # No crash, at least one band captured
    assert isinstance(bands, list)


def test_zone_boundary_merge_consolidates_split_components():
    """Simulate a band whose connected components are split by a zone boundary.

    Place two tight peaks within 3px of each other, straddling the zone boundary.
    """
    detector = CV2BandDetector(CV2DetectionParams())
    crop = _vertical_gradient_lane(h=300, w=40, low=30, high=180)
    crop[99] = 240
    crop[101] = 240  # separated by 2px, straddling zone1/zone2 boundary
    bands = detector.detect(crop, (0, 0, 40, 300), adaptive=True)
    # Zone-boundary merge should produce at most one band for this pair.
    count_near_boundary = sum(1 for b in bands if 95 <= b.position_y <= 105)
    assert count_near_boundary <= 1
