"""Tests for CrossLaneConsensusParams and result dataclasses."""

from __future__ import annotations

import uuid

import pytest

from gel_analyzer.services.band_detection.cross_lane_consensus import (
    AnchorFit,
    ConsensusResult,
    CrossLaneConsensusParams,
)


def test_params_defaults():
    p = CrossLaneConsensusParams()
    assert p.min_lane_support == 0.66
    assert p.anchor_min_support == 0.66
    assert p.y_tolerance_px == 5
    assert p.enable_smile_correction is True
    assert p.soft_vote_min_snr == 0.5
    assert p.lane_type == "sample"


def test_params_validation_raises_on_out_of_range():
    with pytest.raises(ValueError):
        CrossLaneConsensusParams(min_lane_support=2.0).validate()
    with pytest.raises(ValueError):
        CrossLaneConsensusParams(anchor_min_support=-0.1).validate()
    with pytest.raises(ValueError):
        CrossLaneConsensusParams(y_tolerance_px=1).validate()
    with pytest.raises(ValueError):
        CrossLaneConsensusParams(soft_vote_min_snr=5.0).validate()
    with pytest.raises(ValueError):
        CrossLaneConsensusParams(lane_type="bogus").validate()


def test_from_dict_missing_lane_type_defaults_to_sample():
    restored = CrossLaneConsensusParams.from_dict({"y_tolerance_px": 6})
    assert restored.lane_type == "sample"


def test_from_dict_normalizes_lane_type_case():
    restored = CrossLaneConsensusParams.from_dict({"lane_type": "LADDER"})
    assert restored.lane_type == "ladder"


def test_lane_type_round_trip():
    p = CrossLaneConsensusParams(lane_type="all")
    assert CrossLaneConsensusParams.from_dict(p.to_dict()).lane_type == "all"


def test_anchor_fit_shape():
    a = AnchorFit(y_mean=350.0, n_lanes=3, fit_kind="quadratic", coefficients=[0.1, 0.2, 0.3])
    assert a.fit_kind == "quadratic"
    assert len(a.coefficients) == 3


def test_consensus_result_has_run_id():
    r = ConsensusResult(
        run_id=uuid.uuid4(),
        added_bands=[],
        anchor_fits=[],
        fallback_tier=0,
        skipped_lanes_no_signal=[],
        consensus_positions_count=0,
        duration_ms=0.0,
    )
    assert r.fallback_tier == 0
    assert r.run_id is not None


def test_params_serialization_roundtrip():
    p = CrossLaneConsensusParams(
        min_lane_support=0.70,
        anchor_min_support=0.55,
        y_tolerance_px=4,
        enable_smile_correction=False,
        soft_vote_min_snr=0.8,
        lane_type="ladder",
    )
    d = p.to_dict()
    restored = CrossLaneConsensusParams.from_dict(d)
    assert restored == p
