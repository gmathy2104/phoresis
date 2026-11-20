"""Tests for SavedComparison model."""

from datetime import timedelta

import pytest

from django.db import IntegrityError
from django.utils import timezone

from gel_analyzer.models import SavedComparison, SavedComparisonLane


@pytest.mark.django_db
class TestSavedComparison:
    """Tests for SavedComparison model."""

    def test_create_saved_comparison(self, test_user, sample_lane):
        """Test basic creation with a lane."""
        comp = SavedComparison.objects.create(
            name="Test Comparison",
            created_by=test_user,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
        assert comp.pk is not None
        assert comp.lane_count == 1
        assert comp.name == "Test Comparison"

    def test_str_representation(self, test_user, sample_lane):
        """Test __str__ includes name and lane count."""
        comp = SavedComparison.objects.create(
            name="My Comparison",
            created_by=test_user,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
        assert "My Comparison" in str(comp)
        assert "1 lanes" in str(comp)

    def test_ordered_lanes_preserved(self, test_user, complete_analysis):
        """Test that ordered_lanes returns lanes in saved order."""
        lanes = list(complete_analysis.lanes.filter(lane_type="SAMPLE").order_by("lane_number")[:3])
        assert len(lanes) >= 3

        comp = SavedComparison.objects.create(
            name="Order Test",
            created_by=test_user,
        )

        # Add in reverse order
        for i, lane in enumerate(reversed(lanes)):
            SavedComparisonLane.objects.create(saved_comparison=comp, lane=lane, order=i)

        ordered = list(comp.ordered_lanes)
        assert ordered == list(reversed(lanes))

    def test_is_public_default_false(self, test_user):
        """Test that is_public defaults to False."""
        comp = SavedComparison.objects.create(
            name="Private",
            created_by=test_user,
        )
        assert comp.is_public is False

    def test_view_settings_json_roundtrip(self, test_user):
        """Test that view_settings JSON survives save/load."""
        settings = {
            "normalization_mode": "total",
            "x_axis_mode": "mw",
            "poi_only": True,
        }
        comp = SavedComparison.objects.create(
            name="Settings Test",
            created_by=test_user,
            view_settings=settings,
        )
        comp.refresh_from_db()
        assert comp.view_settings["normalization_mode"] == "total"
        assert comp.view_settings["x_axis_mode"] == "mw"
        assert comp.view_settings["poi_only"] is True

    def test_unique_together_prevents_duplicate_lane(self, test_user, sample_lane):
        """Test that the same lane cannot be added twice to a comparison."""
        comp = SavedComparison.objects.create(
            name="Unique Test",
            created_by=test_user,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
        with pytest.raises(IntegrityError):
            SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=1)

    def test_cascade_delete_lane(self, test_user, sample_lane):
        """Test that deleting a lane removes through rows but comparison survives."""
        comp = SavedComparison.objects.create(
            name="Cascade Test",
            created_by=test_user,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
        assert comp.lane_count == 1

        # Delete the lane
        sample_lane.delete()

        # Comparison still exists but has no lanes
        comp.refresh_from_db()
        assert comp.lane_count == 0

    def test_cascade_delete_comparison(self, test_user, sample_lane):
        """Test that deleting a comparison removes through rows."""
        comp = SavedComparison.objects.create(
            name="Delete Test",
            created_by=test_user,
        )
        SavedComparisonLane.objects.create(saved_comparison=comp, lane=sample_lane, order=0)
        comp_pk = comp.pk

        comp.delete()

        assert not SavedComparison.objects.filter(pk=comp_pk).exists()
        assert not SavedComparisonLane.objects.filter(saved_comparison_id=comp_pk).exists()

    def test_history_tracking(self, test_user):
        """Test that SimpleHistory tracks changes."""
        comp = SavedComparison.objects.create(
            name="History Test",
            created_by=test_user,
        )
        assert hasattr(comp, "history")

        comp.name = "Updated Name"
        comp.save()

        assert comp.history.count() >= 1

    def test_ordering_by_updated_at(self, test_user):
        """Test default ordering is by -updated_at."""
        comp1 = SavedComparison.objects.create(
            name="First",
            created_by=test_user,
        )
        comp2 = SavedComparison.objects.create(
            name="Second",
            created_by=test_user,
        )
        # Windows' clock ticks every ~15 ms, so the re-save below could get the same
        # updated_at as the second row (a tie, in any order). Move the second row an
        # hour back: a queryset update() bypasses auto_now.
        SavedComparison.objects.filter(pk=comp2.pk).update(updated_at=timezone.now() - timedelta(hours=1))

        # Update first one to make it newer
        comp1.name = "First Updated"
        comp1.save()

        comparisons = list(SavedComparison.objects.filter(created_by=test_user))
        assert comparisons[0].pk == comp1.pk
