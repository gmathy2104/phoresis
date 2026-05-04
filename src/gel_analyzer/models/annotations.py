"""
Lane and Band annotation models.
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Lane(models.Model):
    """
    A lane within a gel image.

    Lanes can be detected by YOLO or manually annotated.
    Each lane has a type and geometry (rectangle, quadrilateral, or polygon).
    """

    class LaneType(models.TextChoices):
        """Lane type choices."""

        SAMPLE = "SAMPLE", "Sample Lane"
        LADDER = "LADDER", "MW Ladder"
        EMPTY = "EMPTY", "Empty Lane"
        CONTROL = "CONTROL", "Control"
        DOT = "DOT", "Dot (for Dot Blots)"

    class DetectionSource(models.TextChoices):
        """Detection source choices."""

        MANUAL = "MANUAL", "Manual Annotation"
        YOLO = "YOLO", "YOLO Detection"

    class LaneShape(models.TextChoices):
        """Lane shape choices."""

        RECTANGLE = "RECTANGLE", "Rectangle"
        QUADRILATERAL = "QUADRILATERAL", "Quadrilateral"
        POLYGON = "POLYGON", "Polygon"

    class ProteinLoadType(models.TextChoices):
        """Protein load type choices."""

        TOTAL = "TOTAL", "Total Protein"
        POI = "POI", "Protein of Interest"
        HOST_CELL = "HOST_CELL", "Host Cell Protein"
        OTHER = "OTHER", "Other"

    # Link to analysis
    analysis = models.ForeignKey("GelAnalysis", on_delete=models.CASCADE, related_name="lanes")

    # Lane identification
    lane_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)], help_text="Lane number (1-indexed from left)"
    )
    lane_type = models.CharField(max_length=20, choices=LaneType.choices, default=LaneType.SAMPLE)

    # Detection source
    detection_source = models.CharField(max_length=20, choices=DetectionSource.choices, default=DetectionSource.MANUAL)
    confidence = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Detection confidence (0-1) if auto-detected",
    )

    # Geometry - shape and coordinates
    lane_shape = models.CharField(
        max_length=20,
        choices=LaneShape.choices,
        default=LaneShape.RECTANGLE,
        help_text="Shape type: rectangle (default), quadrilateral, or polygon",
    )

    # Rectangle coordinates (used when lane_shape=RECTANGLE)
    x = models.PositiveIntegerField(help_text="X coordinate of top-left corner")
    y = models.PositiveIntegerField(help_text="Y coordinate of top-left corner")
    width = models.PositiveIntegerField(help_text="Lane width in pixels")
    height = models.PositiveIntegerField(help_text="Lane height in pixels")

    # Polygon coordinates (used when lane_shape=QUADRILATERAL or POLYGON)
    polygon = models.JSONField(
        null=True, blank=True, help_text="Polygon points [[x1,y1], [x2,y2], ...] for non-rectangle shapes"
    )

    # Sample conditions
    is_reduced = models.BooleanField(
        null=True, blank=True, help_text="Reduced (True) or Non-reduced (False) conditions"
    )

    # Protein load
    protein_load_ug = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0)], help_text="Protein load in micrograms"
    )
    protein_load_type = models.CharField(
        max_length=20, choices=ProteinLoadType.choices, blank=True, help_text="Type of protein loaded"
    )

    # Free-text sample identifier (Phoresis has no central sample registry).
    sample_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Sample name / identifier",
    )

    # Extensible per-lane metadata (loading conditions, batch ID, replicate
    # tag, etc.). Keeps Lane open to future analyzer-specific extensions
    # without schema migrations. Example: {"replicate": "R1", "batch": "B42"}.
    sample_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Free-form per-lane metadata (replicate, batch, conditions, ...)",
    )

    # Notes
    notes = models.TextField(blank=True)

    # Ladder template for MW reference lanes
    ladder_template = models.ForeignKey(
        "gel_analyzer.LadderTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lanes",
        help_text="MW ladder template (for LADDER type lanes only)",
    )

    class Meta:
        verbose_name = "Lane"
        verbose_name_plural = "03. Lanes"
        ordering = ["analysis", "lane_number"]
        # Note: No unique_together - lane_number is managed by renumber_lanes()
        # The database 'id' field is the stable identifier used in API calls
        indexes = [
            models.Index(fields=["analysis", "lane_type"], name="ga_lane_type_idx"),
        ]

    def __str__(self):
        return f"Lane {self.lane_number} ({self.get_lane_type_display()})"

    @property
    def display_name(self) -> str:
        """Get display name for the lane."""
        if self.sample_name:
            return f"Lane {self.lane_number}: {self.sample_name}"
        return f"Lane {self.lane_number} ({self.get_lane_type_display()})"

    @property
    def x_center(self) -> float:
        """Horizontal center of the lane bounding box (pixels)."""
        return self.x + self.width / 2

    @property
    def bbox(self) -> dict:
        """Get bounding box as dict (for rectangle shapes or computed from polygon)."""
        if self.lane_shape == self.LaneShape.RECTANGLE:
            return {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            }
        elif self.polygon:
            # Compute bbox from polygon points
            xs = [p[0] for p in self.polygon]
            ys = [p[1] for p in self.polygon]
            return {
                "x": min(xs),
                "y": min(ys),
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
            }
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @property
    def has_polygon(self) -> bool:
        """Check if lane uses polygon geometry."""
        return self.lane_shape in (self.LaneShape.QUADRILATERAL, self.LaneShape.POLYGON)

    @property
    def condition_display(self) -> str:
        """Get display string for reduced/non-reduced condition."""
        if self.is_reduced is True:
            return "Reduced"
        elif self.is_reduced is False:
            return "Non-reduced"
        return ""


class Band(models.Model):
    """
    A band within a lane.

    Bands can be detected by YOLO/SAM or manually annotated.
    Stores position, MW estimation, and densitometry results.
    """

    class DetectionSource(models.TextChoices):
        """Detection source choices."""

        MANUAL = "MANUAL", "Manual Annotation"
        YOLO = "YOLO", "YOLO Detection"
        SAM = "SAM", "SAM Segmentation"
        AUTO = "CV2", "Auto (d1/d2)"
        PROFILE = "PROFILE", "Profile Peak Detection"
        CV2_VISION = "CV2V", "CV2 Vision Detection"
        HYBRID = "HYBRID", "Hybrid Detection"

    class BandType(models.TextChoices):
        """Band type for densitometry classification."""

        MW_REFERENCE = "MW_REFERENCE", "MW Reference"
        POI = "POI", "Protein of Interest"
        OTHER = "OTHER", "Other"

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to lane
    lane = models.ForeignKey("Lane", on_delete=models.CASCADE, related_name="bands")

    # Detection source
    detection_source = models.CharField(max_length=20, choices=DetectionSource.choices, default=DetectionSource.MANUAL)
    confidence = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Detection confidence (0-1)",
    )

    # Band classification for densitometry
    band_type = models.CharField(
        max_length=20,
        choices=BandType.choices,
        default=BandType.OTHER,
        help_text="Band classification for densitometry analysis",
    )

    # Band identification
    band_number = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Band number (1-indexed from top of lane)"
    )

    # Position (relative to image, Y is migration distance)
    position_y = models.PositiveIntegerField(help_text="Y position of band center in image")

    # Geometry (can be bbox or polygon)
    polygon = models.JSONField(
        default=list, blank=True, help_text="Polygon points [[x1,y1], [x2,y2], ...] if segmented"
    )
    bbox_x = models.PositiveIntegerField(null=True, blank=True, help_text="Bounding box X")
    bbox_y = models.PositiveIntegerField(null=True, blank=True, help_text="Bounding box Y")
    bbox_width = models.PositiveIntegerField(null=True, blank=True, help_text="Bounding box width")
    bbox_height = models.PositiveIntegerField(null=True, blank=True, help_text="Bounding box height")

    # MW estimation
    estimated_mw_kda = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0)], help_text="Estimated molecular weight in kDa"
    )
    mw_estimation_method = models.CharField(max_length=50, blank=True, help_text="Method used for MW estimation")

    # Densitometry
    intensity_raw = models.FloatField(null=True, blank=True, help_text="Raw integrated intensity (sum of pixel values)")
    intensity_peak = models.FloatField(null=True, blank=True, help_text="Peak intensity value at band center")
    intensity_normalized = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Normalized intensity (0-100%)",
    )
    area_pixels = models.PositiveIntegerField(null=True, blank=True, help_text="Band area in pixels")

    # User-defined label
    label = models.CharField(max_length=100, blank=True, help_text="User-assigned label for the band")

    # Notes
    notes = models.TextField(blank=True)

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_gel_bands"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-band algorithmic provenance (hybrid_phase, consensus_run_id, ...).",
    )

    class Meta:
        verbose_name = "Band"
        verbose_name_plural = "04. Bands"
        ordering = ["lane", "position_y"]
        indexes = [
            models.Index(fields=["lane"], name="ga_band_lane_idx"),
            models.Index(fields=["detection_source"], name="ga_band_source_idx"),
        ]

    def __str__(self):
        if self.estimated_mw_kda:
            return f"Band at {self.position_y}px (~{self.estimated_mw_kda:.1f} kDa)"
        return f"Band at {self.position_y}px"

    @property
    def has_polygon(self) -> bool:
        """Check if band has polygon segmentation."""
        return bool(self.polygon)

    @property
    def bbox(self) -> dict | None:
        """Get bounding box as dict if available."""
        if self.bbox_x is not None:
            return {
                "x": self.bbox_x,
                "y": self.bbox_y,
                "width": self.bbox_width,
                "height": self.bbox_height,
            }
        return None


class MWMarker(models.Model):
    """
    Molecular weight marker definitions for ladder calibration.

    Stores known MW values for ladder bands.
    """

    # Link to lane (must be LADDER type)
    lane = models.ForeignKey(
        "Lane", on_delete=models.CASCADE, related_name="mw_markers", limit_choices_to={"lane_type": "LADDER"}
    )

    # Link to corresponding band (optional)
    band = models.OneToOneField("Band", on_delete=models.CASCADE, null=True, blank=True, related_name="mw_marker")

    # Known MW value
    mw_kda = models.FloatField(validators=[MinValueValidator(0)], help_text="Known molecular weight in kDa")

    # Position for mapping (if not linked to band)
    position_y = models.PositiveIntegerField(help_text="Y position in image")

    class Meta:
        verbose_name = "MW Marker"
        verbose_name_plural = "05. MW Markers"
        ordering = ["lane", "-mw_kda"]

    def __str__(self):
        return f"{self.mw_kda} kDa marker"
