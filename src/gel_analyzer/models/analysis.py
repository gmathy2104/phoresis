"""
GelAnalysis model for tracking analysis workflow and results.
"""

import uuid

from simple_history.models import HistoricalRecords

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class GelAnalysis(models.Model):
    """
    Analysis session for a gel image.

    Tracks the workflow from draft through completion/approval,
    MW calibration settings, and overall analysis results.
    """

    class Status(models.TextChoices):
        """Analysis status choices."""

        DRAFT = "DRAFT", "Draft"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to gel image
    gel_image = models.ForeignKey("GelImage", on_delete=models.CASCADE, related_name="analyses")

    # Analysis name/version
    name = models.CharField(max_length=255, blank=True, help_text="Optional analysis name/version")

    # Status workflow
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # MW Calibration
    ladder_lane_number = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Lane number containing the MW ladder"
    )
    ladder_type = models.CharField(
        max_length=100, blank=True, help_text="Ladder type (e.g., 'Precision Plus Protein', 'PageRuler')"
    )
    calibration_coefficients = models.JSONField(
        default=dict, blank=True, help_text="MW calibration curve coefficients (log-linear fit)"
    )
    calibration_r_squared = models.FloatField(null=True, blank=True, help_text="R-squared value of the calibration fit")

    # YOLO detection results (stored for reference)
    yolo_detection_results = models.JSONField(default=dict, blank=True, help_text="Raw YOLO detection output")
    yolo_gel_type_inference = models.CharField(
        max_length=20, blank=True, help_text="Gel type inferred from YOLO classes"
    )

    # Anti-HCP western readout: every lane's HCP signal is also given in % of this
    # lane's, chosen by the user. SET_NULL: deleting the lane leaves the analysis
    # without a reference.
    readout_reference_lane = models.ForeignKey(
        "Lane",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Reference lane of an anti-HCP western: each lane's HCP signal is also given in % of this one",
    )

    # Summary results
    total_lanes = models.PositiveSmallIntegerField(default=0, help_text="Total number of lanes detected/annotated")
    total_bands = models.PositiveSmallIntegerField(default=0, help_text="Total number of bands detected/annotated")

    # Notes
    notes = models.TextField(blank=True)

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_gel_analyses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Approval tracking
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_gel_analyses"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Audit trail
    history = HistoricalRecords(history_change_reason_field=models.TextField(null=True))

    class Meta:
        verbose_name = "Gel Analysis"
        verbose_name_plural = "02. Gel Analyses"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gel_image"], name="ga_analysis_image_idx"),
            models.Index(fields=["status"], name="ga_analysis_status_idx"),
            models.Index(fields=["created_at"], name="ga_analysis_created_idx"),
        ]

    def __str__(self):
        name_part = f" - {self.name}" if self.name else ""
        return f"Analysis of {self.gel_image.original_filename}{name_part} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        # A percentage of another membrane's lane compares two exposures: meaningless.
        if self.readout_reference_lane_id is not None and self.readout_reference_lane.analysis_id != self.pk:
            raise ValidationError({"readout_reference_lane": "The reference lane must be a lane of this analysis."})

    @property
    def is_editable(self) -> bool:
        """Check if analysis can be edited."""
        return self.status in [self.Status.DRAFT, self.Status.IN_PROGRESS]

    @property
    def is_approvable(self) -> bool:
        """Check if analysis can be approved."""
        return self.status == self.Status.COMPLETED

    def update_counts(self):
        """Update total_lanes and total_bands from related objects."""
        self.total_lanes = self.lanes.count()
        self.total_bands = sum(lane.bands.count() for lane in self.lanes.all())
        self.save(update_fields=["total_lanes", "total_bands"])

    def renumber_lanes(self):
        """
        Renumber lanes based on their X position (left to right).

        This ensures lane numbers reflect physical position on the gel,
        which is critical for scientific interpretation.
        """
        lanes = list(self.lanes.order_by("x"))
        for i, lane in enumerate(lanes, start=1):
            if lane.lane_number != i:
                lane.lane_number = i
                lane.save(update_fields=["lane_number"])
