"""Tests for hybrid band detection API endpoints."""

import json

import pytest

from django.urls import reverse

from gel_analyzer.models import Band

# ---------------------------------------------------------------------------
# Preview endpoint (no DB write)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHybridDetectionPreview:
    """Test the hybrid detection preview endpoint (no DB write)."""

    def test_preview_requires_login(self, client, sample_lane):
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 302  # redirect to login

    def test_preview_returns_200_with_bands(self, client, test_user, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 5}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "bands" in data
        assert "band_count" in data
        assert "summary" in data
        assert "params_used" in data
        assert data["lane_id"] == sample_lane.pk
        assert data["lane_number"] == sample_lane.lane_number

    def test_preview_does_not_save_bands(self, client, test_user, sample_lane):
        """Preview must not write any bands to the database."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        count_before = Band.objects.filter(lane=sample_lane).count()
        client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 5}}),
            content_type="application/json",
        )
        count_after = Band.objects.filter(lane=sample_lane).count()
        assert count_before == count_after

    def test_preview_band_count_matches_bands_list(self, client, test_user, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 7}}),
            content_type="application/json",
        )
        data = response.json()
        assert data["band_count"] == len(data["bands"])

    def test_preview_invalid_json_returns_400(self, client, test_user, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        response = client.post(url, data="not-json", content_type="application/json")
        assert response.status_code == 400

    def test_preview_nonexistent_lane_returns_404(self, client, test_user):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": 999999})
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 404

    def test_preview_accepts_empty_params(self, client, test_user, sample_lane):
        """Empty params object should use defaults without error."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# Save endpoint (writes HYBRID bands to DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHybridDetectionSave:
    """Test the hybrid detection save endpoint."""

    def test_save_requires_login(self, client, sample_lane):
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": sample_lane.pk})
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 302

    def test_save_persists_hybrid_bands(self, client, test_user, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 7}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # DB count must match reported band_count
        saved = Band.objects.filter(lane=sample_lane, detection_source="HYBRID")
        assert saved.count() == data["band_count"]

    def test_save_returns_summary(self, client, test_user, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 5}}),
            content_type="application/json",
        )
        data = response.json()
        assert "summary" in data

    def test_save_deletes_existing_hybrid_bands_by_default(self, client, test_user, sample_lane):
        """Second save should replace previous HYBRID bands (delete_existing=True default)."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": sample_lane.pk})
        payload = json.dumps({"params": {"sensitivity": 5}})

        # First save
        r1 = client.post(url, data=payload, content_type="application/json")
        count1 = Band.objects.filter(lane=sample_lane, detection_source="HYBRID").count()

        # Second save — should replace, not accumulate
        r2 = client.post(url, data=payload, content_type="application/json")
        count2 = Band.objects.filter(lane=sample_lane, detection_source="HYBRID").count()

        assert r1.status_code == 200
        assert r2.status_code == 200
        # After two saves the count must equal the second result, not double
        assert count2 == r2.json()["band_count"]
        # Not double the first count
        assert count2 <= count1 + 5  # loose upper bound — detection is deterministic

    def test_save_nonexistent_lane_returns_404(self, client, test_user):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": 999999})
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 404

    def test_save_replaces_auto_bands_preserves_manual(self, client, test_user, sample_lane):
        """Hybrid save must delete ALL auto-detected bands (CV2, d1/d2 AUTO,
        PROFILE, CV2_VISION, YOLO, SAM, prior HYBRID) while preserving
        MANUAL annotations. This prevents the "old band kept its size" bug
        where prior auto-detection rows stacked with new hybrid sub-bands.
        """
        # Seed prior auto-detected bands from every non-manual source
        prior_bands = {}
        for src in [
            Band.DetectionSource.AUTO,  # d1/d2 ('CV2')
            Band.DetectionSource.CV2_VISION,  # 'CV2V'
            Band.DetectionSource.PROFILE,  # 'PROFILE'
            Band.DetectionSource.YOLO,
            Band.DetectionSource.SAM,
            Band.DetectionSource.HYBRID,
        ]:
            b = Band.objects.create(
                lane=sample_lane,
                detection_source=src,
                position_y=100,
                bbox_x=10,
                bbox_y=95,
                bbox_width=40,
                bbox_height=10,
                created_by=test_user,
            )
            prior_bands[src] = b.id

        # Seed a MANUAL band — must be preserved
        manual_band = Band.objects.create(
            lane=sample_lane,
            detection_source=Band.DetectionSource.MANUAL,
            position_y=200,
            bbox_x=10,
            bbox_y=195,
            bbox_width=40,
            bbox_height=10,
            created_by=test_user,
        )

        client.force_login(test_user)
        url = reverse(
            "gel_analyzer:api_detect_bands_hybrid_lane_save",
            kwargs={"pk": sample_lane.pk},
        )
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 5}}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # MANUAL band must still exist
        assert Band.objects.filter(id=manual_band.id).exists(), (
            "MANUAL band was deleted — hybrid save must preserve user annotations"
        )

        # No bands from any auto source should remain with the seeded id —
        # they were all replaced. Prior HYBRID is also gone (replaced by
        # fresh hybrid output).
        remaining_ids = set(Band.objects.filter(lane=sample_lane).values_list("id", flat=True))
        for src, prior_id in prior_bands.items():
            assert prior_id not in remaining_ids, (
                f"Prior {src} band (id={prior_id}) was not replaced — "
                f"auto-detected bands must not stack across hybrid saves"
            )

    def test_save_rejected_when_analysis_not_editable(self, client, test_user, gel_analysis, sample_lane):
        from gel_analyzer.models import GelAnalysis

        gel_analysis.status = GelAnalysis.Status.APPROVED
        gel_analysis.save()

        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_lane_save", kwargs={"pk": sample_lane.pk})
        response = client.post(
            url,
            data=json.dumps({"params": {"sensitivity": 5}}),
            content_type="application/json",
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Async endpoint (starts Celery task)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHybridDetectionAsync:
    """Test the async hybrid detection endpoint (CELERY_TASK_ALWAYS_EAGER=True in tests)."""

    def test_async_requires_login(self, client, gel_analysis):
        url = reverse("gel_analyzer:api_detect_bands_hybrid_async", kwargs={"pk": gel_analysis.pk})
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 302

    def test_async_returns_task_id(self, client, test_user, gel_analysis, sample_lane):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_async", kwargs={"pk": gel_analysis.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "params": {"sensitivity": 5},
                    "lane_ids": [sample_lane.pk],
                    "save_results": False,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "task_id" in data
        assert data["analysis_id"] == str(gel_analysis.pk)

    def test_async_nonexistent_analysis_returns_404(self, client, test_user):
        import uuid

        client.force_login(test_user)
        url = reverse(
            "gel_analyzer:api_detect_bands_hybrid_async",
            kwargs={"pk": uuid.uuid4()},
        )
        response = client.post(url, data="{}", content_type="application/json")
        assert response.status_code == 404

    def test_async_invalid_lane_ids_returns_400(self, client, test_user, gel_analysis):
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_async", kwargs={"pk": gel_analysis.pk})
        response = client.post(
            url,
            data=json.dumps({"lane_ids": ["bad", "ids"]}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_async_save_rejected_when_not_editable(self, client, test_user, gel_analysis, sample_lane):
        from gel_analyzer.models import GelAnalysis

        gel_analysis.status = GelAnalysis.Status.APPROVED
        gel_analysis.save()

        client.force_login(test_user)
        url = reverse("gel_analyzer:api_detect_bands_hybrid_async", kwargs={"pk": gel_analysis.pk})
        response = client.post(
            url,
            data=json.dumps(
                {
                    "lane_ids": [sample_lane.pk],
                    "save_results": True,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 403
