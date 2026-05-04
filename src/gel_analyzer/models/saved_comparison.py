"""
Saved Comparison models for gel_analyzer.

Allows users to persist lane comparison configurations for later retrieval.
Stores lane references (ordered), view settings, and sharing configuration.
"""

import uuid

from simple_history.models import HistoricalRecords

from django.conf import settings
from django.db import models


class SavedComparison(models.Model):
    """
    A saved comparison of multiple gel lanes.

    Stores the lane selection, display order, view settings,
    and sharing configuration for reloading comparison views.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, help_text="User-defined name for this comparison")
    description = models.TextField(blank=True, help_text="Optional description of the comparison purpose")

    # Lanes (ordered M2M via through model)
    lanes = models.ManyToManyField(
        "Lane",
        through="SavedComparisonLane",
        related_name="saved_comparisons",
        help_text="Lanes included in this comparison (ordered)",
    )

    # View settings (normalization, axis mode, etc.)
    view_settings = models.JSONField(
        default=dict, blank=True, help_text="Saved view settings: normalization_mode, x_axis_mode, poi_only, etc."
    )

    # Sharing
    is_public = models.BooleanField(default=False, help_text="If True, visible to all users; otherwise only to creator")

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="saved_comparisons"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # History
    history = HistoricalRecords(history_change_reason_field=models.TextField(null=True))

    class Meta:
        verbose_name = "Saved Comparison"
        verbose_name_plural = "09. Saved Comparisons"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["created_by", "-updated_at"], name="ga_saved_comp_user_idx"),
            models.Index(fields=["is_public", "-updated_at"], name="ga_saved_comp_public_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.lanes.count()} lanes)"

    @property
    def lane_count(self):
        return self.lanes.count()

    @property
    def ordered_lanes(self):
        """Return lanes in saved order."""
        return self.lanes.order_by("savedcomparisonlane__order")


class SavedComparisonLane(models.Model):
    """
    Through model for SavedComparison <-> Lane M2M.
    Preserves lane display order within a comparison.
    """

    saved_comparison = models.ForeignKey(SavedComparison, on_delete=models.CASCADE)
    lane = models.ForeignKey("Lane", on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0, help_text="Display order (0-indexed)")

    class Meta:
        verbose_name = "Saved Comparison Lane"
        verbose_name_plural = "Saved Comparison Lanes"
        ordering = ["saved_comparison", "order"]
        unique_together = [("saved_comparison", "lane")]
        indexes = [
            models.Index(fields=["saved_comparison", "order"], name="ga_saved_comp_lane_ord_idx"),
        ]

    def __str__(self):
        return f"{self.saved_comparison.name} - Lane {self.lane_id} (#{self.order})"
