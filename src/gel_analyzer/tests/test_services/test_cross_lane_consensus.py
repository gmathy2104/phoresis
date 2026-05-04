"""Integration tests for CrossLaneConsensus.run() — end-to-end consensus flow."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane
from gel_analyzer.services.band_detection.cross_lane_consensus import CrossLaneConsensus, CrossLaneConsensusParams


@pytest.fixture
def synthetic_analysis(db, django_user_model):
    user = django_user_model.objects.create(username="consensus_user")
    image = GelImage.objects.create(
        uploaded_by=user,
        original_filename="consensus_test.tif",
        width=800,
        height=600,
    )
    analysis = GelAnalysis.objects.create(gel_image=image, created_by=user)
    # Create 5 lanes with bands at matching positions, lane 4 missing one band.
    lanes = []
    for i in range(5):
        lane = Lane.objects.create(
            analysis=analysis,
            lane_number=i + 1,
            x=50 + i * 100,
            y=0,
            width=40,
            height=500,
        )
        lanes.append(lane)
    consensus_ys = [100, 200, 300]
    for i, lane in enumerate(lanes):
        for y in consensus_ys:
            if i == 3 and y == 200:  # lane 4 missing y=200
                continue
            Band.objects.create(
                lane=lane,
                position_y=y,
                bbox_x=lane.x,
                bbox_y=y - 5,
                bbox_width=40,
                bbox_height=10,
                detection_source="HYBRID",
            )
    return analysis, lanes


class _FakePeak:
    """Stand-in for DetectedPeak used by derivative detector mocks."""

    y_position = 200
    snr = 3.0
    height = 100
    prominence = 10
    width_px = 4
    left_valley = 0
    right_valley = 0
    left_base = 0
    right_base = 0


class _FakePeakHighSNR(_FakePeak):
    snr = 10.0


@pytest.mark.django_db
def test_insufficient_lanes_returns_empty_result(synthetic_analysis):
    """If <3 lanes have bands, abort with empty result, no exception."""
    analysis, lanes = synthetic_analysis
    # Delete bands on 3 lanes so only 2 remain.
    for lane in lanes[:3]:
        lane.bands.all().delete()
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    result = svc.run(analysis, dry_run=True)
    assert result.added_bands == []
    assert result.consensus_positions_count == 0


@pytest.mark.django_db
def test_run_id_generated_consistently(synthetic_analysis):
    analysis, _ = synthetic_analysis
    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    with patch.object(CrossLaneConsensus, "_load_lane_crop", return_value=np.zeros((500, 40, 3), dtype=np.uint8)):
        r1 = svc.run(analysis, dry_run=True)
        r2 = svc.run(analysis, dry_run=True)
    assert r1.run_id != r2.run_id  # each run() call gets a fresh id


@pytest.mark.django_db
def test_soft_vote_adds_band_when_signal_present(synthetic_analysis):
    analysis, lanes = synthetic_analysis
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        result = svc.run(analysis, dry_run=True)
    # Lane 4 (index 3) was missing y=200; should now have a candidate.
    assert result.consensus_positions_count >= 1
    assert any(b._lane_id == lanes[3].id for b in result.added_bands)


@pytest.mark.django_db
def test_dry_run_does_not_persist(synthetic_analysis):
    analysis, _ = synthetic_analysis
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        before = Band.objects.filter(lane__analysis=analysis).count()
        svc.run(analysis, dry_run=True)
        after = Band.objects.filter(lane__analysis=analysis).count()
    assert before == after


@pytest.mark.django_db
def test_apply_persists_with_metadata(synthetic_analysis):
    analysis, lanes = synthetic_analysis
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        result = svc.run(analysis, dry_run=False)

    persisted = Band.objects.filter(lane=lanes[3], metadata__consensus_run_id=str(result.run_id))
    assert persisted.exists()
    b = persisted.first()
    assert b.metadata.get("hybrid_phase") == "cross_lane_filled"
    assert b.metadata.get("consensus_run_id") == str(result.run_id)


@pytest.mark.django_db
def test_idempotence_second_apply_no_duplicates(synthetic_analysis):
    analysis, _ = synthetic_analysis
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        svc.run(analysis, dry_run=False)
        count_after_first = Band.objects.filter(lane__analysis=analysis).count()
        svc.run(analysis, dry_run=False)
        count_after_second = Band.objects.filter(lane__analysis=analysis).count()
    assert count_after_first == count_after_second


@pytest.mark.django_db
def test_confidence_capped_at_0_6(synthetic_analysis):
    analysis, _ = synthetic_analysis
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeakHighSNR()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        result = svc.run(analysis, dry_run=True)
    for b in result.added_bands:
        assert b.confidence <= 0.6


@pytest.mark.django_db
def test_ladder_lanes_excluded_from_sample_consensus(synthetic_analysis):
    """A LADDER lane must not pollute the min_lane_support denominator nor
    receive soft-vote bands when lane_type='sample' (the default)."""
    analysis, lanes = synthetic_analysis
    # Promote lane 5 to LADDER and strip its bands.
    lanes[4].lane_type = Lane.LaneType.LADDER
    lanes[4].save()
    lanes[4].bands.all().delete()
    from gel_analyzer.services.band_detection import derivative_detector as dd_module

    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([_FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
    ):
        svc = CrossLaneConsensus(CrossLaneConsensusParams())
        result = svc.run(analysis, dry_run=True)
    # 4 sample lanes, 3 share y=200 → 3/4 = 0.75 ≥ 0.66 consensus survives.
    assert result.consensus_positions_count >= 1
    # No band should target the ladder lane.
    assert not any(b._lane_id == lanes[4].id for b in result.added_bands)


@pytest.mark.django_db
def test_lane_type_all_includes_ladder(synthetic_analysis):
    """With lane_type='all' the service falls back to the legacy unscoped behavior."""
    analysis, lanes = synthetic_analysis
    lanes[4].lane_type = Lane.LaneType.LADDER
    lanes[4].save()
    svc = CrossLaneConsensus(CrossLaneConsensusParams(lane_type="all"))
    with patch.object(
        CrossLaneConsensus,
        "_load_lane_crop",
        return_value=np.zeros((500, 40, 3), dtype=np.uint8),
    ):
        result = svc.run(analysis, dry_run=True)
    # Smoke: returns a result object without raising. Ladder kept in pool.
    assert result is not None


@pytest.mark.django_db
def test_polarity_detection_prefers_sample_lane(synthetic_analysis):
    """_resolve_bg_type must pick a SAMPLE lane for polarity, even when the
    first lane by ordering is a LADDER."""
    analysis, lanes = synthetic_analysis
    # Make lane 0 a ladder; lane 1 remains SAMPLE.
    lanes[0].lane_type = Lane.LaneType.LADDER
    lanes[0].save()

    svc = CrossLaneConsensus(CrossLaneConsensusParams())
    captured = {}

    def fake_loader(self, lane, analysis):
        captured.setdefault("first_call_lane_id", lane.id)
        return np.zeros((500, 40, 3), dtype=np.uint8)

    with patch.object(CrossLaneConsensus, "_load_lane_crop", new=fake_loader):
        svc._resolve_bg_type(analysis)

    assert captured["first_call_lane_id"] != lanes[0].id
    assert captured["first_call_lane_id"] == lanes[1].id
