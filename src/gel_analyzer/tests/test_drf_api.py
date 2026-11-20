"""
DRF API Tests for Gel Analyzer.

Tests the formal REST API at /api/v1/.
Uses existing fixtures from conftest.py.

Run with: pytest src/gel_analyzer/tests/test_drf_api.py -v
"""

import pytest
from rest_framework import status

pytestmark = pytest.mark.integration


class TestGelImageAPI:
    """Tests for GelImage DRF endpoints."""

    def test_list_images(self, authenticated_api_client, gel_image):
        url = "/api/v1/images/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) >= 1

    def test_retrieve_image(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(gel_image.id)
        assert "display_file_url" in response.data
        assert "thumbnail_url" in response.data

    def test_retrieve_image_has_dimensions(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.data["width"] == 400
        assert response.data["height"] == 500

    def test_delete_image(self, gel_writer_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = gel_writer_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_patch_gel_type_refused_when_it_contradicts_the_assay(self, gel_writer_api_client, gel_image):
        """DRF never runs GelImage.clean(): without this guard a PATCH would leave a western-typed
        image on a PURITY assay, and its lanes would write a purity."""
        from gel_analyzer.models import GelAssay, GelImage

        assay = GelAssay.objects.create(
            name="Test SDS purity", gel_type=GelImage.GelType.SDS_PAGE, readout=GelAssay.Readout.PURITY
        )
        gel_image.assay = assay
        gel_image.save(update_fields=["assay"])
        url = f"/api/v1/images/{gel_image.id}/"

        response = gel_writer_api_client.patch(url, {"gel_type": "WESTERN_BLOT"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "gel_type" in response.data
        gel_image.refresh_from_db()
        assert gel_image.gel_type == GelImage.GelType.SDS_PAGE

        # The same writer, a gel type the assay agrees with: accepted — the 400 was the guard.
        response = gel_writer_api_client.patch(url, {"gel_type": "SDS_PAGE"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_schema_accessible(self, authenticated_api_client):
        url = "/api/schema/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_swagger_ui_accessible(self, authenticated_api_client):
        url = "/api/docs/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK


class TestGelAnalysisAPI:
    """Tests for GelAnalysis DRF endpoints."""

    def test_list_analyses(self, authenticated_api_client, gel_analysis):
        url = "/api/v1/analyses/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data

    def test_retrieve_analysis_full_tree(self, authenticated_api_client, complete_analysis):
        url = f"/api/v1/analyses/{complete_analysis.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "gel_image" in response.data
        assert "lanes" in response.data
        assert len(response.data["lanes"]) > 0

    def test_retrieve_analysis_has_image_urls(self, authenticated_api_client, complete_analysis):
        url = f"/api/v1/analyses/{complete_analysis.id}/"
        response = authenticated_api_client.get(url)
        img = response.data["gel_image"]
        assert "display_file_url" in img
        assert "thumbnail_url" in img

    def test_create_analysis(self, gel_writer_api_client, gel_image):
        url = "/api/v1/analyses/"
        data = {"gel_image": str(gel_image.id), "name": "API Analysis"}
        response = gel_writer_api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED

    def test_analysis_status_transition(self, gel_writer_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"
        response = gel_writer_api_client.post(url, {"status": "IN_PROGRESS"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_analysis_invalid_transition(self, gel_writer_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"
        response = gel_writer_api_client.post(url, {"status": "APPROVED"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_plain_gel_writer_cannot_approve_a_completed_analysis(
        self, gel_writer_api_client, gel_analysis, gel_analyzer_group, django_user_model
    ):
        """Regression (2026-10-05): the REST status door checked only the transition table, so any
        gel writer approved a COMPLETED analysis — no QA check, no approver recorded."""
        from django.contrib.auth.models import Group

        from gel_analyzer.models import GelAnalysis
        from gel_analyzer.services.analysis_status import GEL_QA_TEAM

        gel_analysis.status = GelAnalysis.Status.COMPLETED
        gel_analysis.save(update_fields=["status"])
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"

        response = gel_writer_api_client.post(url, {"status": "APPROVED"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.COMPLETED
        assert gel_analysis.approved_by is None

        # A Gel QA Team member, NOT staff (so the group is what admits them): approved, and recorded.
        qa_user = django_user_model.objects.create_user(username="gel_qa", password="x")
        qa_user.groups.add(gel_analyzer_group, Group.objects.get_or_create(name=GEL_QA_TEAM)[0])
        gel_writer_api_client.force_authenticate(user=qa_user)

        response = gel_writer_api_client.post(url, {"status": "APPROVED"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.APPROVED
        assert gel_analysis.approved_by_id == qa_user.pk
        assert gel_analysis.approved_at is not None

    def test_only_the_creator_can_take_a_completed_analysis_back_to_in_progress(
        self, gel_writer_api_client, gel_analysis, gel_analyzer_group, test_user, django_user_model
    ):
        """COMPLETED → IN_PROGRESS pulls an analysis out of QA review: its creator's alone, like reopen."""
        from gel_analyzer.models import GelAnalysis

        gel_analysis.status = GelAnalysis.Status.COMPLETED
        gel_analysis.save(update_fields=["status"])
        url = f"/api/v1/analyses/{gel_analysis.id}/status/"
        other = django_user_model.objects.create_user(username="other_writer", password="x")
        other.groups.add(gel_analyzer_group)
        gel_writer_api_client.force_authenticate(user=other)

        response = gel_writer_api_client.post(url, {"status": "IN_PROGRESS"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.COMPLETED

        gel_writer_api_client.force_authenticate(user=test_user)
        response = gel_writer_api_client.post(url, {"status": "IN_PROGRESS"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        gel_analysis.refresh_from_db()
        assert gel_analysis.status == GelAnalysis.Status.IN_PROGRESS

    def test_delete_analysis(self, gel_writer_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/"
        response = gel_writer_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestLaneAPI:
    """Tests for Lane DRF endpoints."""

    def test_retrieve_lane(self, authenticated_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["lane_type"] == "SAMPLE"
        assert "bands" in response.data

    def test_update_lane(self, gel_writer_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = gel_writer_api_client.patch(url, {"sample_name": "Updated"}, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_delete_lane(self, gel_writer_api_client, sample_lane):
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = gel_writer_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestBandAPI:
    """Tests for Band DRF endpoints."""

    def test_retrieve_band(self, authenticated_api_client, band):
        url = f"/api/v1/bands/{band.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "bbox" in response.data
        assert response.data["estimated_mw_kda"] == 55.0

    def test_delete_band(self, gel_writer_api_client, band):
        url = f"/api/v1/bands/{band.id}/"
        response = gel_writer_api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestCalibrationAPI:
    """Tests for Calibration endpoint on GelAnalysisViewSet."""

    def test_calibration_not_found(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/calibration/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDetectionAPI:
    """Tests for Detection endpoints on GelAnalysisViewSet."""

    def test_detection_params_defaults(self, authenticated_api_client, db):
        url = "/api/v1/analyses/detection-params/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "smoothing_window" in response.data


class TestDensitometryAPI:
    """Tests for Densitometry endpoints on GelAnalysisViewSet."""

    def test_densitometry_results_not_found(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/densitometry/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestLadderTemplateAPI:
    """Tests for LadderTemplate DRF endpoints."""

    def test_list_templates(self, authenticated_api_client, db):
        url = "/api/v1/ladder-templates/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_default_template_not_found(self, authenticated_api_client, db):
        url = "/api/v1/ladder-templates/default/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestSavedComparisonAPI:
    """Tests for SavedComparison DRF endpoints."""

    def test_list_comparisons(self, authenticated_api_client, db):
        url = "/api/v1/comparisons/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_another_accounts_private_comparison_is_hidden_and_a_member_cannot_delete_theirs(
        self, gel_writer_api_client, test_user
    ):
        """The ViewSet listed every PRIVATE comparison -- handing out the UUIDs the report route took --
        and let any group member PATCH/DELETE anyone's (2026-10-12). The caller is a MEMBER, so a 403
        here is the owner rule, not the group gate."""
        from django.contrib.auth import get_user_model

        from gel_analyzer.models import SavedComparison

        owner = get_user_model().objects.create_user(username="comparison_owner", password="x")
        private = SavedComparison.objects.create(name="Their private", created_by=owner)
        public = SavedComparison.objects.create(name="Their public", created_by=owner, is_public=True)
        mine = SavedComparison.objects.create(name="Mine", created_by=test_user)
        url = "/api/v1/comparisons/"

        listed = {row["id"] for row in gel_writer_api_client.get(url).data["results"]}
        assert {str(mine.pk), str(public.pk)} <= listed
        assert str(private.pk) not in listed
        assert gel_writer_api_client.get(f"{url}{private.pk}/").status_code == status.HTTP_404_NOT_FOUND

        assert gel_writer_api_client.delete(f"{url}{private.pk}/").status_code == status.HTTP_404_NOT_FOUND
        assert gel_writer_api_client.delete(f"{url}{public.pk}/").status_code == status.HTTP_403_FORBIDDEN
        assert SavedComparison.objects.filter(pk__in=[private.pk, public.pk]).count() == 2

        # The caller's own still goes: the refusals above were the rule, not a closed door.
        assert gel_writer_api_client.delete(f"{url}{mine.pk}/").status_code == status.HTTP_204_NO_CONTENT


# =============================================================================
# Block A enrichment — new field assertions (Tasks A1–A8)
# =============================================================================


class TestGelImageNewFields:
    """Task A1: GelImageDetailSerializer must expose file_size_bytes + description."""

    def test_image_detail_exposes_file_size_bytes(self, authenticated_api_client, gel_image):
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "file_size_bytes" in response.data

    def test_image_detail_exposes_description(self, authenticated_api_client, gel_image):
        gel_image.description = "batch 17, lane spacing 5mm"
        gel_image.save(update_fields=["description"])
        url = f"/api/v1/images/{gel_image.id}/"
        response = authenticated_api_client.get(url)
        assert response.data["description"] == "batch 17, lane spacing 5mm"


class TestLaneNewFields:
    """Task A2: LaneSerializer must expose confidence + loading_volume_ul."""

    def test_lane_exposes_confidence_and_loading_volume(self, authenticated_api_client, sample_lane):
        sample_lane.confidence = 0.87
        sample_lane.loading_volume_ul = 20.0
        sample_lane.save(update_fields=["confidence", "loading_volume_ul"])
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["confidence"] == 0.87
        assert response.data["loading_volume_ul"] == 20.0

    def test_lane_write_accepts_loading_volume_ul(self, gel_writer_api_client, sample_lane):
        # Writable: critical for µg/mL → µg conversion in quantification.
        url = f"/api/v1/lanes/{sample_lane.id}/"
        response = gel_writer_api_client.patch(url, {"loading_volume_ul": 15.5}, format="json")
        assert response.status_code == status.HTTP_200_OK
        sample_lane.refresh_from_db()
        assert sample_lane.loading_volume_ul == 15.5


class TestBandNewFields:
    """Task A3: BandSerializer must expose audit trail + metadata."""

    def test_band_exposes_audit_and_metadata(self, authenticated_api_client, band):
        band.band_number = 3
        band.mw_estimation_method = "log_linear"
        band.confidence = 0.91
        band.metadata = {"hybrid_phase": "cv2", "consensus_run_id": "abc-123"}
        band.save(update_fields=["band_number", "mw_estimation_method", "confidence", "metadata"])
        url = f"/api/v1/bands/{band.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["band_number"] == 3
        assert response.data["mw_estimation_method"] == "log_linear"
        assert response.data["confidence"] == 0.91
        assert response.data["metadata"] == {"hybrid_phase": "cv2", "consensus_run_id": "abc-123"}
        assert "created_at" in response.data
        assert "updated_at" in response.data


class TestGelAnalysisNewFields:
    """Task A5: GelAnalysisDetailSerializer must expose calibration_r_squared + approval workflow."""

    def test_analysis_detail_exposes_r_squared_and_approval(self, authenticated_api_client, gel_analysis):
        gel_analysis.calibration_r_squared = 0.997
        gel_analysis.notes = "reviewed under low-light"
        gel_analysis.rejection_reason = ""
        gel_analysis.save(update_fields=["calibration_r_squared", "notes", "rejection_reason"])
        url = f"/api/v1/analyses/{gel_analysis.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["calibration_r_squared"] == 0.997
        assert response.data["notes"] == "reviewed under low-light"
        assert "approved_by" in response.data
        assert "approved_at" in response.data
        assert "rejection_reason" in response.data
        assert "yolo_gel_type_inference" in response.data


class TestDensitometryResultSerializer:
    """Task A6: Band densitometry endpoint must return the formalized payload."""

    def test_band_densitometry_returns_full_payload(self, authenticated_api_client, band):
        from gel_analyzer.models import DensitometryResult

        DensitometryResult.objects.create(
            band=band,
            peak_center_y=100.0,
            peak_amplitude=200.0,
            peak_sigma=5.0,
            fwhm=11.77,
            integrated_area=2500.0,
            background_area=100.0,
            corrected_area=2400.0,
            fit_r_squared=0.98,
            snr=15.5,
            relative_percent_lane=42.0,
            relative_percent_gel=12.0,
            estimated_amount=8.7,
            estimated_amount_unit="UG",
        )
        url = f"/api/v1/bands/{band.id}/densitometry/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        for key in (
            "peak_center_y",
            "peak_amplitude",
            "peak_sigma",
            "fwhm",
            "integrated_area",
            "background_area",
            "corrected_area",
            "fit_r_squared",
            "snr",
            "relative_percent_lane",
            "relative_percent_gel",
            "estimated_amount",
            "estimated_amount_unit",
            "computed_at",
        ):
            assert key in response.data, f"missing key: {key}"
        assert response.data["estimated_amount"] == 8.7
        assert response.data["estimated_amount_unit"] == "UG"


class TestMWMarkersEndpoint:
    """Task A7: GET /api/v1/analyses/<id>/mw-markers/ returns ladder markers."""

    def test_mw_markers_endpoint_returns_markers(self, authenticated_api_client, complete_analysis):
        url = f"/api/v1/analyses/{complete_analysis.id}/mw-markers/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        # complete_analysis fixture creates 5 markers in the LADDER lane.
        assert len(response.data) == 5
        first = response.data[0]
        for key in ("id", "lane", "band", "mw_kda", "position_y"):
            assert key in first


class TestLadderTemplateNewFields:
    """Task A4: LadderTemplateDetailSerializer must expose audit fields."""

    def test_ladder_template_detail_exposes_audit(self, authenticated_api_client, test_user, db):
        from gel_analyzer.models import LadderTemplate

        tmpl = LadderTemplate.objects.create(
            name="Test Template",
            code="TEST_A4",
            manufacturer="Acme",
            is_active=True,
            is_global=False,
            created_by=test_user,
        )
        url = f"/api/v1/ladder-templates/{tmpl.id}/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "created_by" in response.data
        assert "created_at" in response.data
        assert "updated_at" in response.data


class TestQuantificationEndpoints:
    """Task A8: function-based quantification endpoints respond with the
    documented shape."""

    def test_quantification_root_get_returns_active_or_null(self, authenticated_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/quantification/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"active": None}

    def test_quantification_preview_422_when_no_calibration_bands(self, gel_writer_api_client, gel_analysis):
        url = f"/api/v1/analyses/{gel_analysis.id}/quantification/preview/"
        response = gel_writer_api_client.post(url, {"method": "LINEAR", "unit": "UG"}, format="json")
        # No CALIBRATION-typed bands → fit fails → 422 with the result dict.
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data.get("success") is False

    def test_quantification_history_404_for_bad_analysis_id(self, authenticated_api_client, db):
        import uuid as _uuid

        url = f"/api/v1/analyses/{_uuid.uuid4()}/quantification/history/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# Schema regression guard (Task A9)
# =============================================================================


class TestSchemaRegression:
    """Spectacular schema must validate and include our new fields."""

    def test_schema_includes_loading_volume_ul(self, authenticated_api_client, db):
        # /api/schema/ is wired through gel_analyzer.urls
        url = "/api/schema/"
        response = authenticated_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        body = response.content.decode("utf-8")
        # New writable Lane field
        assert "loading_volume_ul" in body
        # New read-only Band field
        assert "mw_estimation_method" in body
        # Quantification serializer
        assert "ProteinQuantCalibration" in body or "quantification" in body.lower()


class TestApprovedAnalysisIsFinal:
    """Owner, 2026-10-05: Gel Total is no longer a normalization, and an APPROVED analysis is final --
    no densitometry run, no quantification save (services/analysis_status.py)."""

    def test_doors_refuse_gel_total_and_any_change_to_an_approved_analysis(
        self, gel_writer_api_client, three_calib_points_analysis
    ):
        from gel_analyzer.models import DensitometryJob, GelAnalysis, ProteinQuantCalibration
        from gel_analyzer.services.analysis_status import APPROVED_IS_FINAL

        analysis = three_calib_points_analysis
        run_url = f"/api/v1/analyses/{analysis.id}/densitometry/run/"
        quant_url = f"/api/v1/analyses/{analysis.id}/quantification/"

        # Gel Total is refused with its reason, before any job is queued
        response = gel_writer_api_client.post(run_url, {"params": {"normalization_method": "gel_total"}}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Gel Total" in response.data["detail"]

        # Not approved yet: the quantification saves
        response = gel_writer_api_client.post(quant_url, {"method": "LINEAR", "unit": "UG"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        calib_id = response.data["id"]

        GelAnalysis.objects.filter(pk=analysis.pk).update(status=GelAnalysis.Status.APPROVED)
        refused = [
            gel_writer_api_client.post(run_url, {"params": {}}, format="json"),
            gel_writer_api_client.post(quant_url, {"method": "LINEAR", "unit": "UG"}, format="json"),
            gel_writer_api_client.delete(f"{quant_url}{calib_id}/"),
        ]
        # The approval's own message, not the group gate's 403
        assert [(r.status_code, (r.data or {}).get("detail")) for r in refused] == [(403, APPROVED_IS_FINAL)] * 3
        assert not DensitometryJob.objects.filter(analysis=analysis).exists()
        calibrations = ProteinQuantCalibration.objects.filter(analysis=analysis)
        assert [(str(c.id), c.is_active) for c in calibrations] == [(str(calib_id), True)]
