"""Integration tests for cross-lane consensus API endpoints."""

from __future__ import annotations

import io
import json
import uuid
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile

from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane


def _make_png_upload() -> SimpleUploadedFile:
    """Create a minimal valid PNG upload so GelImage.original_file can be saved."""
    buf = io.BytesIO()
    Image.fromarray(np.zeros((10, 10), dtype=np.uint8), mode="L").save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(
        name="clc_test.png",
        content=buf.read(),
        content_type="image/png",
    )


@pytest.fixture
def analysis_with_bands(db, django_user_model):
    user = django_user_model.objects.create_user(username="clc_user", password="pw")
    image = GelImage.objects.create(
        uploaded_by=user,
        original_file=_make_png_upload(),
        original_filename="f.tif",
        width=800,
        height=600,
    )
    analysis = GelAnalysis.objects.create(gel_image=image, created_by=user)
    for i in range(5):
        lane = Lane.objects.create(
            analysis=analysis,
            lane_number=i + 1,
            x=50 + i * 100,
            y=0,
            width=40,
            height=500,
        )
        for y in (100, 200, 300):
            if i == 3 and y == 200:
                continue
            Band.objects.create(
                lane=lane,
                position_y=y,
                bbox_x=lane.x,
                bbox_y=y - 5,
                bbox_width=40,
                bbox_height=10,
                detection_source=Band.DetectionSource.HYBRID,
            )
    return analysis, user


@pytest.mark.django_db
def test_unauthenticated_returns_401(client, analysis_with_bands):
    analysis, _ = analysis_with_bands
    url = f"/analyses/{analysis.id}/cross-lane-consensus/"
    resp = client.post(url, data="{}", content_type="application/json")
    assert resp.status_code in (401, 302)  # login_required may redirect


@pytest.mark.django_db
def test_insufficient_lanes_returns_400(client, analysis_with_bands):
    analysis, user = analysis_with_bands
    # Remove bands on 3 lanes so <3 remain with bands
    lane_ids = list(analysis.lanes.all()[:3].values_list("id", flat=True))
    Band.objects.filter(lane_id__in=lane_ids).delete()
    client.force_login(user)
    url = f"/analyses/{analysis.id}/cross-lane-consensus/"
    resp = client.post(
        url,
        data=json.dumps({"params": {}, "dry_run": True}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "insufficient_lanes"


@pytest.mark.django_db
def test_invalid_params_returns_400(client, analysis_with_bands):
    analysis, user = analysis_with_bands
    client.force_login(user)
    url = f"/analyses/{analysis.id}/cross-lane-consensus/"
    resp = client.post(
        url,
        data=json.dumps({"params": {"min_lane_support": 2.0}, "dry_run": True}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_params"


@pytest.mark.django_db
def test_unknown_analysis_returns_404(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    fake = uuid.uuid4()
    resp = client.post(
        f"/analyses/{fake}/cross-lane-consensus/",
        data="{}",
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_dry_run_does_not_persist(client, analysis_with_bands):
    from gel_analyzer.services.band_detection.cross_lane_consensus import CrossLaneConsensus

    analysis, user = analysis_with_bands
    client.force_login(user)
    before = Band.objects.filter(lane__analysis=analysis).count()
    with (
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
        patch.object(
            CrossLaneConsensus,
            "_resolve_bg_type",
            return_value="dark",
        ),
    ):
        resp = client.post(
            f"/analyses/{analysis.id}/cross-lane-consensus/",
            data=json.dumps({"params": {}, "dry_run": True}),
            content_type="application/json",
        )
    after = Band.objects.filter(lane__analysis=analysis).count()
    assert resp.status_code == 200
    assert before == after
    body = resp.json()
    assert body["added_band_ids"] is None
    assert "run_id" in body["result"]


@pytest.mark.django_db
def test_apply_persists_with_metadata(client, analysis_with_bands):
    from gel_analyzer.services.band_detection import derivative_detector as dd_module
    from gel_analyzer.services.band_detection.cross_lane_consensus import CrossLaneConsensus

    class FakePeak:
        y_position = 200
        snr = 3.0
        height = 100
        prominence = 10
        width_px = 4
        left_valley = 0
        right_valley = 0
        left_base = 0
        right_base = 0

    analysis, user = analysis_with_bands
    client.force_login(user)
    with (
        patch.object(
            dd_module.DerivativeDetector,
            "detect",
            return_value=([FakePeak()], None),
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
        patch.object(
            CrossLaneConsensus,
            "_resolve_bg_type",
            return_value="dark",
        ),
    ):
        resp = client.post(
            f"/analyses/{analysis.id}/cross-lane-consensus/",
            data=json.dumps({"params": {}, "dry_run": False}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    added = resp.json()["added_band_ids"]
    assert len(added) >= 1
    b = Band.objects.get(id=added[0])
    assert b.metadata["hybrid_phase"] == "cross_lane_filled"
    assert "consensus_run_id" in b.metadata


@pytest.mark.django_db
def test_delete_undo_removes_bands_by_run_id(client, analysis_with_bands):
    analysis, user = analysis_with_bands
    run_id = "11111111-2222-3333-4444-555555555555"
    # Manually persist a band with this run_id
    Band.objects.create(
        lane=analysis.lanes.first(),
        position_y=450,
        bbox_x=50,
        bbox_y=445,
        bbox_width=40,
        bbox_height=10,
        detection_source=Band.DetectionSource.HYBRID,
        metadata={"hybrid_phase": "cross_lane_filled", "consensus_run_id": run_id},
    )
    client.force_login(user)
    resp = client.delete(f"/analyses/{analysis.id}/cross-lane-consensus/?run_id={run_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 1


@pytest.mark.django_db
def test_delete_without_run_id_returns_400(client, analysis_with_bands):
    analysis, user = analysis_with_bands
    client.force_login(user)
    resp = client.delete(f"/analyses/{analysis.id}/cross-lane-consensus/")
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_run_id"


@pytest.mark.django_db
def test_delete_unknown_run_id_returns_404(client, analysis_with_bands):
    analysis, user = analysis_with_bands
    client.force_login(user)
    resp = client.delete(f"/analyses/{analysis.id}/cross-lane-consensus/?run_id=nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "run_not_found"
    assert body["deleted_count"] == 0


@pytest.mark.django_db
def test_lane_type_passes_through_to_service(client, analysis_with_bands):
    """The ``lane_type`` key in params must flow to CrossLaneConsensusParams."""
    from gel_analyzer.services.band_detection.cross_lane_consensus import CrossLaneConsensus

    analysis, user = analysis_with_bands
    client.force_login(user)

    captured = {}

    def spy_init(self, params):
        captured["lane_type"] = params.lane_type
        self.params = params

    with (
        patch.object(
            CrossLaneConsensus,
            "__init__",
            new=spy_init,
        ),
        patch.object(
            CrossLaneConsensus,
            "_load_lane_crop",
            return_value=np.zeros((500, 40, 3), dtype=np.uint8),
        ),
        patch.object(
            CrossLaneConsensus,
            "_resolve_bg_type",
            return_value="dark",
        ),
    ):
        resp = client.post(
            f"/analyses/{analysis.id}/cross-lane-consensus/",
            data=json.dumps({"params": {"lane_type": "all"}, "dry_run": True}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert captured["lane_type"] == "all"
