"""The band model the annotation editor runs in the browser: what the server hands out, the bands it builds from the
model's boxes, and how it writes them (views/band_model_api.py, services/band_detection/yolo_bands.py)."""

import json

import pytest

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from gel_analyzer.models import Band, GelAnalysis, Lane, LaneDensitometrySummary
from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL


@pytest.fixture(autouse=True)
def band_model_without_lfs(monkeypatch, request):
    """Where the model file is a Git LFS pointer, take the configuration without proving the file.

    The CI jobs that only test clone without LFS on purpose: the 53 MB model is then a 134-byte
    pointer, the endpoints answer 503 ("its file does not match its configuration") and every test
    below fails on a file it does not test -- they test what the server builds from the model's
    boxes. With the real file (a developer's clone, the image build) nothing is patched and the
    sha256 is verified as in production.
    """
    # The one test of the refusal itself keeps the real verification: a pointer is a mismatch too.
    if request.node.name == "test_model_file_not_matching_settings_is_never_served":
        return
    from gel_analyzer.checks import _is_lfs_pointer
    from gel_analyzer.services import band_model

    if _is_lfs_pointer(band_model.band_model_path(band_model.band_model_config())):
        monkeypatch.setattr("gel_analyzer.views.band_model_api.verified_band_model", band_model.band_model_config)


# One box in the sample lane (x 50, w 40), one in the ladder lane (x 100, w 40).
SAVE_BOXES = [[55, 95, 85, 105, 0.9], [105, 145, 135, 155, 0.8]]


def _save(client, analysis, boxes=SAVE_BOXES, sha256=None):
    body = {
        "model_sha256": sha256 or settings.GEL_ANALYZER_BAND_MODEL["sha256"],
        "image": {"width": analysis.gel_image.width, "height": analysis.gel_image.height},
        "boxes": boxes,
    }
    return client.post(
        reverse("gel_analyzer:api_band_model_save", kwargs={"pk": analysis.pk}),
        data=json.dumps(body),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_browser_path_context_then_preview(client, test_user, gel_analysis, sample_lane, ladder_lane):
    """The browser's path: fetch the model, post its boxes, get lane-wide bands in the classical shape."""
    client.force_login(test_user)
    context = client.get(reverse("gel_analyzer:api_band_model_context", kwargs={"pk": gel_analysis.pk}))
    assert context.status_code == 200
    ctx = context.json()
    assert ctx["model"]["sha256"] == settings.GEL_ANALYZER_BAND_MODEL["sha256"]
    assert ctx["model"]["url"].endswith(settings.GEL_ANALYZER_BAND_MODEL["static_path"])
    assert (ctx["image"]["width"], ctx["image"]["height"]) == (400, 500)

    boxes = [
        [60, 96, 88, 106, 0.6],  # superposed on the next one, less confident, posted first
        [55, 95, 85, 105, 0.90043],  # sample lane (x 50, w 40); a score no rounding leaves as it is
        [105, 145, 135, 155, 0.8],  # ladder lane (x 100, w 40)
        [55, 300, 85, 310, 0.1],  # under the default 0.25
        [300, 200, 340, 210, 0.9],  # in no lane
        [55, 0, 85, 0, 0.9],  # empty, clipped against the edge: what ultralytics returns
    ]
    response = client.post(
        reverse("gel_analyzer:api_band_model_preview", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps({"model_sha256": ctx["model"]["sha256"], "image": ctx["image"], "boxes": boxes}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    counters = ("below_threshold", "empty", "outside_lanes", "superposed", "band_count")
    assert tuple(data[key] for key in counters) == (1, 1, 1, 1, 2)
    sample, ladder = data["lanes"]
    assert (sample["lane_id"], sample["band_type"]) == (sample_lane.pk, "OTHER")
    (band,) = sample["bands"]
    assert (band["bbox_x"], band["bbox_width"], band["bbox_y"], band["bbox_height"]) == (50, 40, 95, 10)
    assert (band["position_y"], band["confidence"]) == (100, 0.9)
    # Unrounded: the page's slider filters the preview on it, and the save compares the same score with the threshold
    # -- rounded, 0.2496 would show at 0.25 a band the save then drops.
    assert band["score"] == 0.90043
    assert (ladder["lane_id"], ladder["band_type"]) == (ladder_lane.pk, "MW_REFERENCE")
    assert [b["bbox_y"] for b in ladder["bands"]] == [145]


@pytest.mark.django_db
def test_model_file_not_matching_settings_is_never_served(client, test_user, gel_analysis):
    client.force_login(test_user)
    wrong = {**settings.GEL_ANALYZER_BAND_MODEL, "sha256": "0" * 64}
    with override_settings(GEL_ANALYZER_BAND_MODEL=wrong):
        response = client.get(reverse("gel_analyzer:api_band_model_context", kwargs={"pk": gel_analysis.pk}))
    assert response.status_code == 503
    body = response.json()
    assert "model" not in body
    assert "does not match" in body["error"] and "E001" in body["error"]


@pytest.mark.django_db
def test_save_writes_classical_rows_keeps_manual_and_stales_densitometry(
    client, test_user, gel_analyzer_group, gel_analysis, sample_lane, ladder_lane, band, yolo_band
):
    """band = hand-drawn (MANUAL), yolo_band = auto-detected, both on the sample lane: the save replaces the second."""
    test_user.groups.add(gel_analyzer_group)
    client.force_login(test_user)
    # The ladder lane holds no band: only the CREATION of its bands can make its densitometry stale.
    for lane in (sample_lane, ladder_lane):
        LaneDensitometrySummary.objects.create(
            lane=lane, total_integrated_area=1000.0, poi_percentage=85.0, band_count=2, computed_by=test_user
        )

    response = _save(client, gel_analysis)

    assert response.status_code == 200
    assert (response.json()["created_count"], response.json()["deleted_count"]) == (2, 1)
    assert Band.objects.filter(pk=band.pk).exists()
    assert not Band.objects.filter(pk=yolo_band.pk).exists()
    new = Band.objects.get(lane=sample_lane, detection_source=Band.DetectionSource.YOLO)
    assert (new.bbox_x, new.bbox_width, new.bbox_y, new.bbox_height, new.position_y) == (50, 40, 95, 10, 100)
    assert (new.band_type, new.confidence, new.created_by) == (Band.BandType.OTHER, 0.9, test_user)
    assert new.metadata["model_sha256"] == settings.GEL_ANALYZER_BAND_MODEL["sha256"]
    assert Band.objects.get(lane=ladder_lane).band_type == Band.BandType.MW_REFERENCE
    assert not LaneDensitometrySummary.objects.filter(lane__in=(sample_lane, ladder_lane)).exists()
    gel_analysis.refresh_from_db()
    assert gel_analysis.total_bands == 3


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["approved", "approved_while_detecting", "other_model"])
def test_save_refusal_writes_nothing(
    case, client, test_user, gel_analyzer_group, gel_analysis, sample_lane, ladder_lane, band, yolo_band, monkeypatch
):
    if case != "reader":
        test_user.groups.add(gel_analyzer_group)
    if case == "approved":
        GelAnalysis.objects.filter(pk=gel_analysis.pk).update(status=GelAnalysis.Status.APPROVED)
    if case == "approved_while_detecting":
        # Approved between the checks at the door and the write: the writer's own check, under the row lock.
        from gel_analyzer.services.file_handler import GelFileHandler

        load = GelFileHandler.load_image_as_array

        def approve_then_load(gel_image, *args, **kwargs):
            GelAnalysis.objects.filter(pk=gel_analysis.pk).update(status=GelAnalysis.Status.APPROVED)
            return load(gel_image, *args, **kwargs)

        monkeypatch.setattr(GelFileHandler, "load_image_as_array", staticmethod(approve_then_load))
    client.force_login(test_user)
    before = sorted(Band.objects.values_list("pk", "detection_source"))

    response = _save(client, gel_analysis, sha256="0" * 64 if case == "other_model" else None)

    status, message = {
        "reader": (403, "write access"),
        "approved": (403, APPROVED_IS_FINAL),
        "approved_while_detecting": (403, APPROVED_IS_FINAL),
        "other_model": (409, "another band model"),
    }[case]
    assert response.status_code == status
    assert message in response.json()["error"]
    assert sorted(Band.objects.values_list("pk", "detection_source")) == before


@pytest.mark.django_db
def test_band_at_the_foot_of_a_tilted_lane_goes_to_that_lane_not_its_neighbour(client, test_user, gel_analysis):
    """Spec 2026-10-10 §5.1: two parallel lanes leaning right overlap by their boxes. A band at the foot of the left
    one has its centre inside both boxes and nearer the right box's centre -- the box rule gave it, and its share of
    the purity, to the neighbouring sample. Read by the row span, it is the left lane's, cut as a slanted slice."""
    a = [[50, 10], [90, 10], [150, 490], [110, 490]]
    b = [[x + 50, y] for x, y in a]
    left, right = (
        Lane.objects.create(
            analysis=gel_analysis,
            lane_number=n,
            lane_type=Lane.LaneType.SAMPLE,
            lane_shape=Lane.LaneShape.QUADRILATERAL,
            polygon=polygon,
            x=polygon[0][0],
            y=10,
            width=100,
            height=480,
        )
        for n, polygon in ((1, a), (2, b))
    )
    client.force_login(test_user)
    body = {
        "model_sha256": settings.GEL_ANALYZER_BAND_MODEL["sha256"],
        "image": {"width": gel_analysis.gel_image.width, "height": gel_analysis.gel_image.height},
        "boxes": [[118, 460, 142, 470, 0.9]],  # centre (130, 465): the left lane's row span there is 106.9-146.9
    }
    response = client.post(
        reverse("gel_analyzer:api_band_model_preview", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(body),
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    lanes = {lane["lane_id"]: lane for lane in response.json()["lanes"]}
    assert (lanes[left.pk]["band_count"], lanes[right.pk]["band_count"]) == (1, 0)
    (band,) = lanes[left.pk]["bands"]
    assert band["polygon"] == [[106, 460], [147, 460], [148, 470], [107, 470]]
    assert (band["bbox_x"], band["bbox_width"], band["bbox_y"], band["bbox_height"]) == (106, 42, 460, 10)
