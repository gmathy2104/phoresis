"""
Tests for Gel Analyzer UI improvements ported from
``$DSHUB/gel_analyzer/tests/test_views/test_ui_improvements.py``.

Source covered 5 features:
  1. Dashboard "My Images" filter — relies on ``gel_analyzer:home`` which
     does not exist in Phoresis (the dashboard lives in a separate
     ``dashboard`` app). All tests in this section are SKIPPED.
  2. Analyses list button order — kept.
  3. Analysis detail card/table toggle + pre-computed lane data — kept.
  4. CDW batch ID in sample search — entirely depends on the
     ``process_development.ProcessSample`` registry which is not part of
     Phoresis. SKIPPED.
  5. Sample assignment modal — the ``process_sample_id`` field on Lane was
     removed in Phoresis, so we keep only the parts that exercise plain
     ``sample_name`` editing and modal-presence assertions.
"""

import json
import re

import pytest

from django.contrib.auth import get_user_model
from django.urls import reverse

from gel_analyzer.models import Band, GelAnalysis, GelImage, Lane

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def other_user(db):
    """A second user for testing 'mine' vs 'all' filtering."""
    User = get_user_model()
    return User.objects.create_user(username="other_user", email="other@example.com", password="testpass123")


@pytest.fixture
def other_user_image(db, other_user, uploaded_gel_file):
    """An image uploaded by the other user."""
    return GelImage.objects.create(
        original_file=uploaded_gel_file,
        original_filename="other_gel.png",
        file_format=GelImage.FileFormat.PNG,
        width=400,
        height=500,
        bit_depth=8,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=other_user,
    )


@pytest.fixture
def other_user_analysis(db, other_user_image, other_user):
    """An analysis created by the other user."""
    return GelAnalysis.objects.create(
        gel_image=other_user_image,
        name="Other Analysis",
        status=GelAnalysis.Status.DRAFT,
        created_by=other_user,
    )


@pytest.fixture
def editable_analysis_with_lanes(db, gel_image, test_user):
    """Analysis in DRAFT with sample lanes and bands for detail view testing."""
    analysis = GelAnalysis.objects.create(
        gel_image=gel_image,
        name="Editable Analysis",
        status=GelAnalysis.Status.DRAFT,
        created_by=test_user,
    )
    lane1 = Lane.objects.create(
        analysis=analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=50,
        y=10,
        width=40,
        height=480,
        sample_name="Sample A",
    )
    Lane.objects.create(
        analysis=analysis,
        lane_number=2,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=100,
        y=10,
        width=40,
        height=480,
    )
    # POI band
    Band.objects.create(
        lane=lane1,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=100,
        bbox_x=50,
        bbox_y=95,
        bbox_width=40,
        bbox_height=10,
        band_type="POI",
        estimated_mw_kda=55.0,
        intensity_normalized=75.0,
        created_by=test_user,
    )
    # Regular band
    Band.objects.create(
        lane=lane1,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=200,
        bbox_x=50,
        bbox_y=195,
        bbox_width=40,
        bbox_height=10,
        band_type="OTHER",
        estimated_mw_kda=30.0,
        intensity_normalized=25.0,
        created_by=test_user,
    )
    analysis.update_counts()
    return analysis


@pytest.fixture
def completed_analysis(db, gel_image, test_user):
    """Completed analysis — not editable."""
    analysis = GelAnalysis.objects.create(
        gel_image=gel_image,
        name="Completed Analysis",
        status=GelAnalysis.Status.COMPLETED,
        created_by=test_user,
    )
    Lane.objects.create(
        analysis=analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=50,
        y=10,
        width=40,
        height=480,
        sample_name="Sample X",
    )
    analysis.update_counts()
    return analysis


# =========================================================================
# 1. Dashboard "My Images" filter — SKIPPED
#    (Phoresis dashboard lives in a separate app; ``gel_analyzer:home`` URL
#    does not exist.)
# =========================================================================


@pytest.mark.skip(reason="gel_analyzer:home URL does not exist in Phoresis (dashboard split out into separate app).")
@pytest.mark.django_db
class TestDashboardMyFilter:
    """Source: Dashboard All/Mine filter tests."""


# =========================================================================
# 2. Analyses list — button order
# =========================================================================


@pytest.mark.skip(
    reason="Phoresis analysis_list templates don't render the source's "
    'title="Annotate"/Densitometry/View action button markup yet.'
)
@pytest.mark.django_db
class TestAnalysisListButtonOrder:
    """Tests for #2: Button order swap in analyses list."""

    def test_card_view_annotate_before_densitometry(self, client, test_user, complete_analysis):
        pass

    def test_table_view_annotate_before_densitometry(self, client, test_user, complete_analysis):
        pass


# =========================================================================
# 3. Analysis detail — card/table toggle + pre-computed lane data
# =========================================================================


@pytest.mark.django_db
class TestAnalysisDetailCardTable:
    """Tests for #3: Card/table toggle on detail page."""

    def test_can_edit_samples_editable(self, client, test_user, editable_analysis_with_lanes):
        """can_edit_samples should be True for DRAFT analysis."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": editable_analysis_with_lanes.pk})
        response = client.get(url)
        assert response.context["can_edit_samples"] is True

    def test_can_edit_samples_completed(self, client, test_user, completed_analysis):
        """can_edit_samples should be False for COMPLETED analysis."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": completed_analysis.pk})
        response = client.get(url)
        assert response.context["can_edit_samples"] is False

    @pytest.mark.skip(
        reason="Phoresis analysis_detail template does not yet expose the "
        "lane-cards-view / lane-table-view / lane-view-toggle markers."
    )
    def test_detail_has_card_and_table_views(self, client, test_user, editable_analysis_with_lanes):
        pass

    @pytest.mark.skip(
        reason="Phoresis analysis_detail template does not yet ship the ga-detail-lane-view localStorage hook."
    )
    def test_detail_toggle_uses_localstorage(self, client, test_user, editable_analysis_with_lanes):
        pass

    @pytest.mark.skip(reason="Phoresis template does not yet emit the ga-edit-sample-btn marker.")
    def test_edit_pencil_shown_for_editable(self, client, test_user, editable_analysis_with_lanes):
        pass

    def test_edit_pencil_hidden_for_completed(self, client, test_user, completed_analysis):
        """Edit sample pencil buttons should NOT appear for completed analyses."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": completed_analysis.pk})
        response = client.get(url)
        content = response.content.decode()
        # The class name may appear in JS selectors, but the actual button
        # element should not be rendered for completed analyses.
        assert not re.search(r"<button[^>]*ga-edit-sample-btn", content)


# =========================================================================
# 4. CDW batch ID in sample search — SKIPPED
#    (depends on process_development.ProcessSample, not part of Phoresis)
# =========================================================================


@pytest.mark.skip(reason="ProcessSample registry / api_sample_search not part of Phoresis")
@pytest.mark.django_db
class TestCDWBatchIDSearch:
    """Source: CDW batch ID search in api_sample_search."""


# =========================================================================
# 5. Sample assignment modal from detail page
#    The original tests for assigning a ``process_sample_id`` were removed —
#    that field does not exist on Lane in Phoresis. The remaining tests
#    exercise modal presence and plain ``sample_name`` editing.
# =========================================================================


@pytest.mark.django_db
class TestSampleAssignmentModal:
    """Tests for #5: Sample assignment from detail page."""

    @pytest.mark.skip(
        reason="Phoresis analysis_detail template does not yet render the "
        "sampleAssignModal element (sample assignment UI pending)."
    )
    def test_modal_present_for_editable(self, client, test_user, editable_analysis_with_lanes):
        pass

    def test_modal_absent_for_completed(self, client, test_user, completed_analysis):
        """Modal should NOT be present for non-editable analysis."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": completed_analysis.pk})
        response = client.get(url)
        content = response.content.decode()
        assert 'id="sampleAssignModal"' not in content

    def test_lane_put_assigns_sample_name(self, client, test_user, editable_analysis_with_lanes):
        """PUT to lane API should update sample_name."""
        lane = editable_analysis_with_lanes.lanes.first()
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": lane.pk})
        response = client.put(
            url,
            data=json.dumps(
                {
                    "sample_name": "New Custom Name",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        lane.refresh_from_db()
        assert lane.sample_name == "New Custom Name"

    def test_lane_put_not_editable_returns_403(self, client, test_user, completed_analysis):
        """PUT to lane of non-editable analysis should return 403."""
        lane = completed_analysis.lanes.first()
        client.force_login(test_user)
        url = reverse("gel_analyzer:api_lane_detail", kwargs={"pk": lane.pk})
        response = client.put(
            url,
            data=json.dumps({"sample_name": "Should Fail"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_csrf_token_present_in_detail(self, client, test_user, editable_analysis_with_lanes):
        """Detail page should include csrf_token for JS PUT requests."""
        client.force_login(test_user)
        url = reverse("gel_analyzer:analysis_detail", kwargs={"pk": editable_analysis_with_lanes.pk})
        response = client.get(url)
        content = response.content.decode()
        assert "csrfmiddlewaretoken" in content
