"""
Densitometry models for quantitative analysis of gel bands.

Models:
- DensitometryResult: Extended densitometry data for a band (OneToOne with Band)
- LaneDensitometrySummary: Summary quantification for a lane
- DensitometryJob: Celery task tracking for async densitometry
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class DensitometryResult(models.Model):
    """
    Extended densitometry data for a band (OneToOne with Band).

    Stores Gaussian fit parameters, integration results, and quality metrics
    for quantitative band analysis.
    """

    # Primary key (UUID for consistency with Band model)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to band (OneToOne)
    band = models.OneToOneField("Band", on_delete=models.CASCADE, related_name="densitometry")

    # Gaussian fit parameters
    peak_center_y = models.FloatField(help_text="Fitted peak center Y position in pixels")
    peak_amplitude = models.FloatField(help_text="Gaussian amplitude (peak height)")
    peak_sigma = models.FloatField(help_text="Gaussian width parameter (sigma)")
    fwhm = models.FloatField(help_text="Full Width at Half Maximum in pixels")

    # Integration results
    integrated_area = models.FloatField(help_text="Total area under the curve (raw)")
    background_area = models.FloatField(default=0.0, help_text="Background contribution to area")
    corrected_area = models.FloatField(help_text="Background-corrected integrated area")

    # Quality metrics
    fit_r_squared = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], help_text="Goodness of fit R-squared (0-1)"
    )
    snr = models.FloatField(validators=[MinValueValidator(0.0)], help_text="Signal-to-noise ratio")

    # Relative quantification (set by normalizer)
    relative_percent_lane = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Percentage of total lane intensity",
    )
    relative_percent_gel = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Percentage of total gel intensity",
    )

    # Metadata
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Densitometry Result"
        verbose_name_plural = "06. Densitometry Results"
        indexes = [
            models.Index(fields=["band"], name="ga_densitometry_band_idx"),
        ]

    def __str__(self):
        return f"Densitometry for Band {self.band_id} (area={self.corrected_area:.1f})"

    @property
    def fit_quality(self) -> str:
        """Return quality indicator based on R-squared value."""
        if self.fit_r_squared >= 0.99:
            return "excellent"
        elif self.fit_r_squared >= 0.95:
            return "good"
        elif self.fit_r_squared >= 0.90:
            return "acceptable"
        elif self.fit_r_squared >= 0.80:
            return "fair"
        else:
            return "poor"


class LaneDensitometrySummary(models.Model):
    """
    Summary quantification for a lane.

    Stores aggregated densitometry data including total area,
    POI (Protein of Interest) calculations, and purity metrics.
    """

    class NormalizationMethod(models.TextChoices):
        """Normalization method choices."""

        LANE_TOTAL = "LANE_TOTAL", "Lane Total"
        GEL_TOTAL = "GEL_TOTAL", "Gel Total"
        LOADING_CONTROL = "LOADING_CONTROL", "Loading Control"
        REFERENCE_BAND = "REFERENCE_BAND", "Reference Band"

    # Link to lane (OneToOne)
    lane = models.OneToOneField("Lane", on_delete=models.CASCADE, related_name="densitometry_summary")

    # Normalization settings
    normalization_method = models.CharField(
        max_length=20,
        choices=NormalizationMethod.choices,
        default=NormalizationMethod.LANE_TOTAL,
        help_text="Method used for relative quantification",
    )
    reference_band_id = models.UUIDField(
        null=True, blank=True, help_text="Reference band ID for LOADING_CONTROL or REFERENCE_BAND normalization"
    )

    # Aggregated metrics
    total_integrated_area = models.FloatField(default=0.0, help_text="Sum of all band corrected areas in lane")
    poi_integrated_area = models.FloatField(null=True, blank=True, help_text="Sum of POI band areas")
    poi_percentage = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Purity percentage (POI / Total * 100)",
    )

    # Other band aggregations
    other_integrated_area = models.FloatField(
        null=True, blank=True, help_text="Sum of OTHER band areas (non-POI, non-reference)"
    )
    mw_reference_area = models.FloatField(null=True, blank=True, help_text="Sum of MW_REFERENCE band areas")

    # Band counts
    band_count = models.PositiveSmallIntegerField(default=0, help_text="Number of bands with densitometry data")
    poi_band_count = models.PositiveSmallIntegerField(default=0, help_text="Number of POI bands")

    # Profile data for charts (JSON)
    profile_data = models.JSONField(null=True, blank=True, help_text="Lane intensity profile data for visualization")

    # Metadata
    computed_at = models.DateTimeField(auto_now=True)
    computed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="computed_lane_densitometries",
    )

    class Meta:
        verbose_name = "Lane Densitometry Summary"
        verbose_name_plural = "07. Lane Densitometry Summaries"
        indexes = [
            models.Index(fields=["lane"], name="ga_lane_densitometry_idx"),
        ]

    def __str__(self):
        purity_str = f", purity={self.poi_percentage:.1f}%" if self.poi_percentage else ""
        return f"Densitometry Summary Lane {self.lane.lane_number} (area={self.total_integrated_area:.1f}{purity_str})"


class DensitometryJob(models.Model):
    """
    Celery task tracking for async densitometry computations.

    Tracks task status, progress, parameters, and results for
    long-running densitometry analyses.
    """

    class Status(models.TextChoices):
        """Job status choices."""

        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to analysis
    analysis = models.ForeignKey("GelAnalysis", on_delete=models.CASCADE, related_name="densitometry_jobs")

    # Celery task info
    task_id = models.CharField(max_length=255, blank=True, help_text="Celery task ID")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Progress percentage (0-100)"
    )

    # Configuration
    params = models.JSONField(default=dict, blank=True, help_text="Densitometry parameters used")
    lane_ids = models.JSONField(null=True, blank=True, help_text="List of lane IDs to process (null = all lanes)")

    # Results
    result = models.JSONField(null=True, blank=True, help_text="Densitometry results summary")
    error_message = models.TextField(blank=True, help_text="Error message if job failed")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True, help_text="When processing started")
    completed_at = models.DateTimeField(
        null=True, blank=True, help_text="When processing completed (success or failure)"
    )

    # User
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_densitometry_jobs",
    )

    class Meta:
        verbose_name = "Densitometry Job"
        verbose_name_plural = "08. Densitometry Jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["analysis", "status"], name="ga_densitometry_job_idx"),
            models.Index(fields=["task_id"], name="ga_densitometry_task_idx"),
        ]

    def __str__(self):
        return f"Densitometry Job {self.id} ({self.get_status_display()})"

    @property
    def is_running(self) -> bool:
        """Check if job is currently running."""
        return self.status in (self.Status.PENDING, self.Status.RUNNING)

    @property
    def is_finished(self) -> bool:
        """Check if job has finished (success or failure)."""
        return self.status in (self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED)

    def mark_running(self):
        """Mark job as running."""
        from django.utils import timezone

        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self, result: dict = None):
        """Mark job as completed successfully."""
        from django.utils import timezone

        self.status = self.Status.COMPLETED
        self.progress = 100
        self.completed_at = timezone.now()
        if result:
            self.result = result
        self.save(update_fields=["status", "progress", "completed_at", "result"])

    def mark_failed(self, error_message: str):
        """Mark job as failed with error message."""
        from django.utils import timezone

        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save(update_fields=["status", "completed_at", "error_message"])

    def update_progress(self, progress: int):
        """Update job progress percentage."""
        self.progress = min(100, max(0, progress))
        self.save(update_fields=["progress"])
