"""Tests for greedy clustering + smile correction inside CrossLaneConsensus."""

from __future__ import annotations

from gel_analyzer.services.band_detection.cross_lane_consensus import (
    AnchorFit,
    CrossLaneConsensus,
    CrossLaneConsensusParams,
)


def _band(lane_id, lane_center_x, y):
    class B:
        pass

    b = B()
    b.lane_id = lane_id
    b.lane_center_x = lane_center_x
    b.y_observed = y
    return b


def test_greedy_cluster_deterministic():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    bands = [
        _band(1, 100, 100),
        _band(2, 200, 102),
        _band(3, 300, 105),
        _band(1, 100, 400),
        _band(2, 200, 402),
    ]
    clusters = svc._greedy_cluster(bands, gap_px=25)
    assert len(clusters) == 2
    ys1 = sorted([b.y_observed for b in clusters[0]])
    ys2 = sorted([b.y_observed for b in clusters[1]])
    assert ys1 == [100, 102, 105]
    assert ys2 == [400, 402]


def test_cluster_gap_exceeded_opens_new_cluster():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    bands = [_band(1, 100, 100), _band(2, 200, 130)]
    clusters = svc._greedy_cluster(bands, gap_px=25)
    assert len(clusters) == 2


def test_anchor_fit_quadratic_on_3_lanes_parabola():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    bands = [
        _band(1, 100, 0.01 * (100 - 200) ** 2 + 350),
        _band(2, 200, 350),
        _band(3, 300, 0.01 * (300 - 200) ** 2 + 350),
    ]
    fit = svc._fit_anchor(bands)
    assert fit.fit_kind == "quadratic"
    assert len(fit.coefficients) == 3


def test_anchor_fit_linear_on_exactly_2_lanes():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    bands = [_band(1, 100, 100), _band(2, 300, 110)]
    fit = svc._fit_anchor(bands)
    assert fit.fit_kind == "linear"
    assert len(fit.coefficients) == 2


def test_duplicate_lane_band_deduplicated_closest_to_mean_kept():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    bands = [
        _band(1, 100, 100),
        _band(1, 100, 120),
        _band(2, 200, 105),
        _band(3, 300, 110),
    ]
    result = svc._dedup_cluster(bands)
    lane1_ys = [b.y_observed for b in result if b.lane_id == 1]
    assert len(lane1_ys) == 1
    assert lane1_ys[0] == 100  # closer to initial mean


def test_smile_offset_interpolation_between_two_anchors():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    anchors = [
        AnchorFit(y_mean=100, n_lanes=3, fit_kind="linear", coefficients=[0.01, 0]),
        AnchorFit(y_mean=500, n_lanes=3, fit_kind="linear", coefficients=[-0.02, 0]),
    ]
    delta = svc._smile_offset(anchors, lane_center_x=200, y_observed=300)
    assert abs(delta - (-1.0)) < 0.01


def test_fallback_tier_0_when_no_anchors():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    assert svc._resolve_fallback_tier(anchors=[]) == 0


def test_fallback_tier_1_single_anchor():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    anchors = [AnchorFit(y_mean=200, n_lanes=3, fit_kind="quadratic", coefficients=[0, 0, 0])]
    assert svc._resolve_fallback_tier(anchors) == 1


def test_fallback_tier_2_multiple_anchors():
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    anchors = [
        AnchorFit(y_mean=100, n_lanes=3, fit_kind="linear", coefficients=[0, 0]),
        AnchorFit(y_mean=400, n_lanes=3, fit_kind="linear", coefficients=[0, 0]),
    ]
    assert svc._resolve_fallback_tier(anchors) == 2
