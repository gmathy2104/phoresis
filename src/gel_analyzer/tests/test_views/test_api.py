"""
Tests for Gel Analyzer non-DRF API endpoints (the legacy ``/api/...`` JSON
views, not the DRF v1 surface).
"""

import json

import pytest

from django.core.files.base import ContentFile
from django.urls import reverse

from gel_analyzer.services.file_handler import GelFileHandler


@pytest.mark.django_db
class TestAPILanes:
    """Tests for api_lanes endpoint."""

    def test_get_lanes_requires_login(self, client, gel_analysis):
        """Test that GET requires authentication."""
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 302

    def test_get_lanes_authenticated(self, client, test_user, gel_analysis):
        """Test GET returns lanes."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert "lanes" in data
        assert data["analysis_id"] == str(gel_analysis.pk)

    def test_get_lanes_with_bands(self, client, test_user, gel_analysis, sample_lane, band):
        """Test GET returns lanes with nested bands."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data["lanes"]) == 1
        assert len(data["lanes"][0]["bands"]) == 1

    def test_post_lane_creates_lane(self, client, test_user, gel_analysis):
        """Test POST creates a new lane."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "x": 100,
                    "y": 50,
                    "width": 50,
                    "height": 400,
                    "lane_number": 1,
                    "lane_type": "SAMPLE",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["lane"]["lane_number"] == 1


@pytest.mark.django_db
class TestAPILaneDetail:
    """Tests for api_lane_detail endpoint."""

    def test_get_lane_detail(self, client, test_user, sample_lane):
        """Test GET returns lane details."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": sample_lane.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["lane"]["lane_number"] == sample_lane.lane_number

    def test_put_lane_updates(self, client, test_user, sample_lane):
        """Test PUT updates lane properties."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": sample_lane.pk})
        response = client.put(
            url,
            data=json.dumps(
                {
                    "sample_name": "Updated Sample",
                    "notes": "Test notes",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lane"]["sample_name"] == "Updated Sample"

    def test_delete_lane(self, client, test_user, sample_lane, gel_analysis):
        """Test DELETE removes lane."""
        client.force_login(test_user)
        pk = sample_lane.pk
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": pk})
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()["success"] is True

        from gel_analyzer.models import Lane

        assert not Lane.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestAPILaneBands:
    """Tests for api_lane_bands endpoint."""

    def test_post_band_creates_band(self, client, test_user, sample_lane):
        """Test POST creates a new band."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_bands", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "polygon": [[50, 100], [90, 100], [90, 120], [50, 120]],
                    "position_y": 110,
                    "label": "Test Band",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["band"]["label"] == "Test Band"


@pytest.mark.django_db
class TestAPIBandDetail:
    """Tests for api_band_detail endpoint."""

    def test_get_band_detail(self, client, test_user, band):
        """Test GET returns band details."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": band.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert float(data["band"]["estimated_mw_kda"]) == 55.0

    def test_put_band_updates(self, client, test_user, band):
        """Test PUT updates band properties."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": band.pk})
        response = client.put(
            url,
            data=json.dumps(
                {
                    "label": "Main Product",
                    "estimated_mw_kda": 60.0,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["band"]["label"] == "Main Product"

    def test_delete_band(self, client, test_user, band, sample_lane):
        """Test DELETE removes band."""
        client.force_login(test_user)
        pk = band.pk
        url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": pk})
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()["success"] is True

        from gel_analyzer.models import Band

        assert not Band.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestAPIAnalysisData:
    """Tests for api_analysis_data endpoint."""

    def test_get_analysis_data(self, client, test_user, complete_analysis):
        """Test GET returns full analysis data."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_analysis_data", kwargs={"pk": complete_analysis.pk})
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert "analysis" in data
        assert "gel_image" in data
        assert "lanes" in data
        assert len(data["lanes"]) > 0


@pytest.mark.django_db
class TestAPIAnalysisStatusTransition:
    """The analysis page's status door (the REST door is tested in test_drf_api.py)."""

    def test_page_reject_is_refused_to_a_non_qa_user_and_recorded_for_qa(
        self, client, test_user, gel_analysis, gel_analyzer_group, django_user_model
    ):
        from django.contrib.auth.models import Group

        from gel_analyzer.models import GelAnalysis
        from gel_analyzer.services.analysis_status import GEL_QA_TEAM

        gel_analysis.status = GelAnalysis.Status.COMPLETED
        gel_analysis.save(update_fields=["status"])
        url = reverse("gel_analyzer:api_analysis_status_transition", kwargs={"pk": gel_analysis.pk})
        # The reason is sent, so the refusal can only be the QA check.
        body = json.dumps({"action": "reject", "reason": "smeared lanes"})
        client.force_login(test_user)

        response = client.post(url, body, content_type="application/json")

        assert response.status_code == 403
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.COMPLETED
        assert gel_analysis.rejection_reason == ""

        # A Gel QA Team member, NOT staff (so the group is what admits them).
        qa_user = django_user_model.objects.create_user(username="gel_qa", password="x")
        qa_user.groups.add(gel_analyzer_group, Group.objects.get_or_create(name=GEL_QA_TEAM)[0])
        client.force_login(qa_user)

        response = client.post(url, body, content_type="application/json")

        assert response.status_code == 200
        assert response.json()["status"] == "REJECTED"
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.REJECTED
        assert gel_analysis.rejection_reason == "smeared lanes"


@pytest.mark.django_db
def test_densitometry_csv_export_answers_the_file_not_a_500_gelimage_has_no_title(
    client, test_user, gel_analysis, band
):
    """From 2026-01-21 to 2026-10-13 every "Export CSV" of the densitometry page answered 500: the file's header
    read ``gel_image.title``, a field GelImage does not have. The page POSTs, as here. The export reads the saved
    densitometry (refused without), so a run is saved first."""
    from gel_analyzer.services.densitometry import DensitometryService

    DensitometryService().analyze_and_save(
        gel_analysis, GelFileHandler.load_image_as_array(gel_analysis.gel_image), test_user
    )
    client.force_login(test_user)
    url = reverse("gel_analyzer:api_export_densitometry", kwargs={"pk": gel_analysis.pk})

    response = client.post(url, data=json.dumps({"format": "csv", "async": False}), content_type="application/json")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    lines = response.content.decode("utf-8").splitlines()
    assert f"# Image,{gel_analysis.gel_image.original_filename}" in lines
    header = next(line for line in lines if line.startswith("Lane,Band ID")).split(",")
    assert header[-5:] == ["Est. Amount", "Est. Unit", "Calibration Range", "Saturated Pixels (%)", "Saturated"]


@pytest.mark.django_db
def test_densitometry_csv_exports_the_saved_loading_control_run_not_a_fresh_lane_total_one(
    client, test_user, gel_analysis, sample_lane, band, gel_analyzer_group
):
    """Owner, 2026-10-13: "Export CSV" re-ran the densitometry with the default parameters, so an analysis run in
    Loading Control came out in Lane Total, under a "# Parameters" block saying lane_total. The file is now the
    saved run, as the page shows it; with no run saved, the page is told to run one, nothing is measured."""
    import csv

    from gel_analyzer.models import Band, DensitometryJob, DensitometryResult
    from gel_analyzer.services.densitometry.export import RUN_THE_DENSITOMETRY_FIRST

    export_url = reverse("gel_analyzer:api_export_densitometry", kwargs={"pk": gel_analysis.pk})
    export_body = json.dumps({"format": "csv", "async": False})
    client.force_login(test_user)

    refused = client.post(export_url, data=export_body, content_type="application/json")
    assert (refused.status_code, refused.json()["detail"]) == (409, RUN_THE_DENSITOMETRY_FIRST)

    # The page's run in Loading Control: the lane's loading control is an MW Reference band on the gel's bar at y=200
    Band.objects.create(
        lane=sample_lane,
        band_type=Band.BandType.MW_REFERENCE,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=200,
        bbox_x=50,
        bbox_y=190,
        bbox_width=40,
        bbox_height=20,
    )
    test_user.groups.add(gel_analyzer_group)
    run = client.post(
        reverse("gel_analyzer:api_run_densitometry_async", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps({"params": {"normalization_method": "loading_control"}}),
        content_type="application/json",
    )
    assert DensitometryJob.objects.get(pk=run.json()["job_id"]).status == DensitometryJob.Status.COMPLETED

    response = client.post(export_url, data=export_body, content_type="application/json")
    assert response.status_code == 200
    rows = list(csv.reader(response.content.decode("utf-8").splitlines()))
    start = rows.index(["# Parameters"]) + 1
    parameters = dict(rows[start : rows.index([], start)])
    assert parameters["normalization_method"] == "loading_control"
    assert parameters["normalization_method by lane"] == "Loading Control: Lane 1"
    assert not any(row[:1] == ["# Not From This Run"] for row in rows)
    details = rows[rows.index(["# Band Details"]) + 1 :]
    band_id, pct_lane = details[0].index("Band ID"), details[0].index("% Lane")
    stored = DensitometryResult.objects.filter(band__lane=sample_lane)
    assert {row[band_id]: row[pct_lane] for row in details[1:]} == {
        str(result.band_id): f"{result.relative_percent_lane:.2f}" for result in stored
    }


@pytest.mark.django_db
def test_image_proxy_revalidates_with_its_etag_and_a_crop_invalidates_it(
    client, test_user, gel_image, sample_gel_png_bytes
):
    """Sample comparison spec §3.7: every add or remove on the comparison page re-renders it, and without a
    validator the browser re-downloads each gel image in full. A matching ETag answers 304; a crop replaces the
    display file, so the old ETag must stop matching and the browser must get the cropped image."""
    gel_image.display_file.save("display/proxy.png", ContentFile(sample_gel_png_bytes), save=True)
    client.force_login(test_user)
    url = reverse("gel_analyzer:api_image_proxy", kwargs={"pk": gel_image.pk})

    first = client.get(url)
    assert first.status_code == 200
    assert first["ETag"]
    assert "private" in first["Cache-Control"] and "no-cache" in first["Cache-Control"]

    assert client.get(url, HTTP_IF_NONE_MATCH=first["ETag"]).status_code == 304

    GelFileHandler.crop_image(gel_image, 0, 0, 200, 200)

    after = client.get(url, HTTP_IF_NONE_MATCH=first["ETag"])
    assert after.status_code == 200
    assert after["ETag"] != first["ETag"]


@pytest.mark.django_db
def test_a_lane_loading_volume_typed_in_the_editor_survives_save_and_reload(
    client, test_user, gel_analysis, sample_lane
):
    """2026-10-12: the editor's Properties panel took a CALIBRATION / CONTROL lane's loading volume, but its Save
    (lane create, bulk update) dropped the field and /data/ never returned it: the typed volume vanished on reload.
    0 is a volume, not an empty field."""
    client.force_login(test_user)
    created = client.post(
        reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(
            {"x": 200, "y": 10, "width": 40, "height": 480, "lane_type": "CONTROL", "loading_volume_ul": 0}
        ),
        content_type="application/json",
    )
    assert created.status_code == 201
    updated = client.put(
        reverse("gel_analyzer:api_bulk_update_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps({"lanes": [{"id": sample_lane.pk, "lane_type": "CALIBRATION", "loading_volume_ul": 20.0}]}),
        content_type="application/json",
    )
    assert updated.status_code == 200

    data = client.get(reverse("gel_analyzer:api_analysis_data", kwargs={"pk": gel_analysis.pk})).json()
    volumes = {lane["id"]: lane["loading_volume_ul"] for lane in data["lanes"]}
    assert volumes == {sample_lane.pk: 20.0, created.json()["lane"]["id"]: 0}


@pytest.mark.django_db
def test_a_lane_write_refuses_a_negative_loading_volume_and_writes_nothing(
    client, test_user, gel_analysis, sample_lane
):
    """The model's MinValueValidator(0) is not run by save(): each editor writer checks the volume itself. One bad
    lane refuses the whole bulk update, the valid lane before it included; the single-lane PUT stores a valid one."""
    from gel_analyzer.models import Lane

    other = Lane.objects.create(analysis=gel_analysis, lane_number=2, x=200, y=10, width=40, height=480)
    client.force_login(test_user)
    detail = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": sample_lane.pk})

    refused = client.put(
        reverse("gel_analyzer:api_bulk_update_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(
            {"lanes": [{"id": other.pk, "loading_volume_ul": 10}, {"id": sample_lane.pk, "loading_volume_ul": -5}]}
        ),
        content_type="application/json",
    )
    assert refused.status_code == 400 and "loading_volume_ul" in refused.json()["error"]
    put_refused = client.put(detail, data=json.dumps({"loading_volume_ul": -1}), content_type="application/json")
    assert put_refused.status_code == 400
    assert list(Lane.objects.filter(analysis=gel_analysis).values_list("loading_volume_ul", flat=True)) == [None, None]

    stored = client.put(detail, data=json.dumps({"loading_volume_ul": 15.5}), content_type="application/json")
    assert stored.status_code == 200 and stored.json()["lane"]["loading_volume_ul"] == 15.5
    sample_lane.refresh_from_db()
    assert sample_lane.loading_volume_ul == 15.5


@pytest.mark.django_db
def test_the_editor_save_left_calibration_points_on_a_sample_lane(
    client, test_user, gel_analysis, sample_lane, calib_lane_with_point
):
    """The editor's lane PUT and bulk update wrote lane_type without the v1 PATCH's guard (until 2026-10-13): a
    CALIBRATION lane became SAMPLE with its calibration points still on it, no error. Both now refuse as the v1 PATCH
    does (409, dependent_band_ids); the bulk refuses the whole request, the valid lane before it included."""
    from gel_analyzer.models import Band, ProteinQuantCalibrationPoint

    calib = calib_lane_with_point
    point = ProteinQuantCalibrationPoint.objects.get(band__lane=calib)
    client.force_login(test_user)

    bulk = client.put(
        reverse("gel_analyzer:api_bulk_update_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(
            {"lanes": [{"id": sample_lane.pk, "sample_name": "renamed"}, {"id": calib.pk, "lane_type": "SAMPLE"}]}
        ),
        content_type="application/json",
    )
    assert bulk.status_code == 409, bulk.content
    assert bulk.json()["dependent_band_ids"] == [str(point.band_id)]
    assert "calibration points" in bulk.json()["error"]

    put = client.put(
        reverse("gel_analyzer:api_lane_detail", kwargs={"pk": calib.pk}),
        data=json.dumps({"lane_type": "SAMPLE"}),
        content_type="application/json",
    )
    assert put.status_code == 409, put.content
    assert put.json()["dependent_band_ids"] == [str(point.band_id)]

    calib.refresh_from_db()
    sample_lane.refresh_from_db()
    assert calib.lane_type == "CALIBRATION"
    assert ProteinQuantCalibrationPoint.objects.filter(band__lane=calib).count() == 1
    assert Band.objects.filter(lane=calib, band_type=Band.BandType.CALIBRATION).count() == 1
    assert sample_lane.sample_name == "Sample 1"


@pytest.mark.django_db
def test_the_editor_save_dropped_the_ladder_template_of_a_lane(client, test_user, gel_analysis, ladder_lane):
    """The bulk update behind the editor's Save ignored ``ladder_template_id`` (until 2026-10-13): a template picked in
    the lane form, or given when the lane became a ladder (PropertiesPanel._followLadderTemplate), never reached the
    server. The template follows the lane type: a lane that stops being a ladder loses it, even when its type is all
    the write sends (the Save; the band auto-promote POI -> SAMPLE, a single-lane PUT)."""
    from gel_analyzer.models import LadderTemplate, Lane

    template = LadderTemplate.objects.create(name="Precision Plus", code="TEST_LADDER_SAVE", manufacturer="Bio-Rad")
    client.force_login(test_user)
    bulk = reverse("gel_analyzer:api_bulk_update_lanes", kwargs={"pk": gel_analysis.pk})

    def put(url, payload):
        return client.put(url, data=json.dumps(payload), content_type="application/json")

    saved = put(bulk, {"lanes": [{"id": ladder_lane.pk, "ladder_template_id": str(template.pk)}]})
    assert saved.status_code == 200 and saved.json()["lanes"][0]["ladder_template_id"] == str(template.pk)
    ladder_lane.refresh_from_db()
    assert ladder_lane.ladder_template_id == template.pk

    for url, payload in (
        (bulk, {"lanes": [{"id": ladder_lane.pk, "lane_type": "SAMPLE"}]}),
        (reverse("gel_analyzer:api_lane_detail", kwargs={"pk": ladder_lane.pk}), {"lane_type": "SAMPLE"}),
    ):
        Lane.objects.filter(pk=ladder_lane.pk).update(lane_type="LADDER", ladder_template=template)
        assert put(url, payload).status_code == 200
        ladder_lane.refresh_from_db()
        assert (url, ladder_lane.lane_type, ladder_lane.ladder_template_id) == (url, "SAMPLE", None)


@pytest.mark.django_db
def test_a_new_ladder_lane_keeps_its_template_and_an_unknown_template_writes_nothing(
    client, test_user, gel_analysis, ladder_lane, sample_lane
):
    """A lane drawn and made a ladder before Save is created with its template (the create dropped it too). One lane
    naming no template refuses the whole bulk update, the valid lane before it included."""
    import uuid

    from gel_analyzer.models import LadderTemplate

    template = LadderTemplate.objects.create(name="Precision Plus", code="TEST_LADDER_NEW", manufacturer="Bio-Rad")
    client.force_login(test_user)

    created = client.post(
        reverse("gel_analyzer:api_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(
            {
                "x": 200,
                "y": 10,
                "width": 40,
                "height": 480,
                "lane_type": "LADDER",
                "ladder_template_id": str(template.pk),
            }
        ),
        content_type="application/json",
    )
    assert created.status_code == 201 and created.json()["lane"]["ladder_template_id"] == str(template.pk)

    refused = client.put(
        reverse("gel_analyzer:api_bulk_update_lanes", kwargs={"pk": gel_analysis.pk}),
        data=json.dumps(
            {
                "lanes": [
                    {"id": ladder_lane.pk, "ladder_template_id": str(template.pk)},
                    {"id": sample_lane.pk, "lane_type": "LADDER", "ladder_template_id": str(uuid.uuid4())},
                ]
            }
        ),
        content_type="application/json",
    )
    assert refused.status_code == 400 and "ladder_template_id" in refused.json()["error"]
    ladder_lane.refresh_from_db()
    sample_lane.refresh_from_db()
    assert (ladder_lane.ladder_template_id, sample_lane.lane_type) == (None, "SAMPLE")


@pytest.mark.django_db
def test_a_band_typed_poi_in_the_editor_kept_its_calibration_point(client, test_user, calib_lane_with_point):
    """The editor's band PUT wrote band_type without the v1 PATCH's rule (until 2026-10-13): a calibration band typed
    POI kept its calibration point, which the lane guard still counted (a 409 for a point no band showed), and the PUT
    stored CALIBRATION with no point. Now the point goes with the type, and CALIBRATION without one is refused."""
    from gel_analyzer.models import Band, ProteinQuantCalibrationPoint

    calib = calib_lane_with_point
    band = Band.objects.get(lane=calib, band_type=Band.BandType.CALIBRATION)
    band_url = reverse("gel_analyzer:api_band_detail", kwargs={"pk": band.pk})
    client.force_login(test_user)

    retyped = client.put(band_url, data=json.dumps({"band_type": "POI"}), content_type="application/json")
    assert retyped.status_code == 200, retyped.content
    assert not ProteinQuantCalibrationPoint.objects.filter(band=band).exists()

    lane = client.put(
        reverse("gel_analyzer:api_lane_detail", kwargs={"pk": calib.pk}),
        data=json.dumps({"lane_type": "SAMPLE"}),
        content_type="application/json",
    )
    assert lane.status_code == 200, lane.content

    refused = client.put(band_url, data=json.dumps({"band_type": "CALIBRATION"}), content_type="application/json")
    assert refused.status_code == 400
    assert "requires a quant_point" in refused.json()["error"]
    band.refresh_from_db()
    calib.refresh_from_db()
    assert (band.band_type, calib.lane_type) == ("POI", "SAMPLE")


@pytest.mark.django_db
def test_a_detection_failure_answers_a_reference_not_the_exception_text(client, test_user, sample_lane):
    """CodeQL #185 (2026-10-31): every ValueError of a band detection -- numpy's, OpenCV's, the image loader's -- was
    answered as "Invalid parameters: <its text>". Only the params' own checks still say what to fix."""
    from gel_analyzer.models import GelImage

    url = reverse("gel_analyzer:api_detect_bands_lane", kwargs={"pk": sample_lane.pk})
    client.force_login(test_user)

    refused = client.post(
        url, data=json.dumps({"params": {"profile_width_percent": 5}}), content_type="application/json"
    )
    assert (refused.status_code, refused.json()["error"]) == (
        400,
        "Invalid parameters: profile_width_percent must be between 10 and 100",
    )

    gel_image = sample_lane.analysis.gel_image
    GelImage.objects.filter(pk=gel_image.pk).update(original_file="", display_file="")  # the loader's ValueError
    failed = client.post(url, data=json.dumps({"params": {}}), content_type="application/json")
    assert failed.status_code == 500
    error = failed.json()["error"]
    assert error.startswith("The band detection failed. (reference PHOR-")
    assert "no image file" not in error and str(gel_image.pk) not in error
