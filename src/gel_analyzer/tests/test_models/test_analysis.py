"""
Tests for GelAnalysis model.
"""

import pytest

from django.utils import timezone

from gel_analyzer.models import GelAnalysis


@pytest.mark.django_db
class TestGelAnalysis:
    """Tests for GelAnalysis model."""

    def test_create_gel_analysis(self, gel_analysis):
        """Test basic GelAnalysis creation."""
        assert gel_analysis.pk is not None
        assert gel_analysis.name == "Test Analysis"
        assert gel_analysis.status == GelAnalysis.Status.DRAFT

    def test_gel_analysis_str(self, gel_analysis):
        """Test GelAnalysis string representation."""
        expected = "Analysis of test_gel.png - Test Analysis (Draft)"
        assert str(gel_analysis) == expected

    def test_gel_analysis_str_no_name(self, gel_image, test_user, db):
        """Test GelAnalysis string without name."""
        analysis = GelAnalysis.objects.create(
            gel_image=gel_image, status=GelAnalysis.Status.DRAFT, created_by=test_user
        )
        assert str(analysis) == "Analysis of test_gel.png (Draft)"

    def test_status_choices(self):
        """Test status choices are valid."""
        assert GelAnalysis.Status.DRAFT == "DRAFT"
        assert GelAnalysis.Status.IN_PROGRESS == "IN_PROGRESS"
        assert GelAnalysis.Status.COMPLETED == "COMPLETED"
        assert GelAnalysis.Status.APPROVED == "APPROVED"
        assert GelAnalysis.Status.REJECTED == "REJECTED"

    def test_is_editable_draft(self, gel_analysis):
        """Test is_editable for draft status."""
        gel_analysis.status = GelAnalysis.Status.DRAFT
        assert gel_analysis.is_editable is True

    def test_is_editable_in_progress(self, gel_analysis):
        """Test is_editable for in_progress status."""
        gel_analysis.status = GelAnalysis.Status.IN_PROGRESS
        assert gel_analysis.is_editable is True

    def test_is_editable_completed(self, gel_analysis):
        """Test is_editable for completed status."""
        gel_analysis.status = GelAnalysis.Status.COMPLETED
        assert gel_analysis.is_editable is False

    def test_is_editable_approved(self, gel_analysis):
        """Test is_editable for approved status."""
        gel_analysis.status = GelAnalysis.Status.APPROVED
        assert gel_analysis.is_editable is False

    def test_is_approvable_completed(self, gel_analysis):
        """Test is_approvable for completed status."""
        gel_analysis.status = GelAnalysis.Status.COMPLETED
        assert gel_analysis.is_approvable is True

    def test_is_approvable_draft(self, gel_analysis):
        """Test is_approvable for draft status."""
        gel_analysis.status = GelAnalysis.Status.DRAFT
        assert gel_analysis.is_approvable is False

    def test_calibration_coefficients_default(self, gel_analysis):
        """Test that calibration_coefficients defaults to empty dict."""
        assert gel_analysis.calibration_coefficients == {}

    def test_yolo_detection_results_default(self, gel_analysis):
        """Test that yolo_detection_results defaults to empty dict."""
        assert gel_analysis.yolo_detection_results == {}

    def test_update_counts(self, complete_analysis):
        """Test update_counts method."""
        # Reset counts
        complete_analysis.total_lanes = 0
        complete_analysis.total_bands = 0
        complete_analysis.save()

        # Update counts
        complete_analysis.update_counts()

        assert complete_analysis.total_lanes == 5  # 1 ladder + 4 samples
        assert complete_analysis.total_bands == 12  # 4 lanes * 3 bands

    def test_approval_workflow(self, gel_analysis, test_user):
        """Test approval workflow fields."""
        gel_analysis.status = GelAnalysis.Status.COMPLETED
        gel_analysis.save()

        # Approve
        gel_analysis.status = GelAnalysis.Status.APPROVED
        gel_analysis.approved_by = test_user
        gel_analysis.approved_at = timezone.now()
        gel_analysis.save()

        assert gel_analysis.approved_by == test_user
        assert gel_analysis.approved_at is not None

    def test_rejection_workflow(self, gel_analysis, test_user):
        """Test rejection workflow fields."""
        gel_analysis.status = GelAnalysis.Status.REJECTED
        gel_analysis.rejection_reason = "Invalid calibration"
        gel_analysis.save()

        assert gel_analysis.status == GelAnalysis.Status.REJECTED
        assert gel_analysis.rejection_reason == "Invalid calibration"


@pytest.mark.django_db
class TestGelAnalysisRelations:
    """Tests for GelAnalysis relationships."""

    def test_lanes_relation(self, gel_analysis, sample_lane, ladder_lane):
        """Test GelAnalysis to Lane relationship."""
        assert gel_analysis.lanes.count() == 2

    def test_cascade_delete_lanes(self, gel_analysis, sample_lane):
        """Test that lanes are deleted when analysis is deleted."""
        lane_id = sample_lane.pk
        gel_analysis.delete()

        from gel_analyzer.models import Lane

        assert not Lane.objects.filter(pk=lane_id).exists()
