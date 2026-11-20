"""
Ladder template models for MW calibration.

Models:
- LadderTemplate: Reusable MW ladder definition (e.g., Bio-Rad Precision Plus)
- LadderBandDefinition: Individual band in a ladder template with known MW
- LadderCalibration: Calibration result linking analysis to ladder template
"""

import uuid

from simple_history.models import HistoricalRecords

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Max, Min


class LadderCategory(models.TextChoices):
    """Categories for MW ladder markers."""

    UNSTAINED = "UNSTAINED", "Unstained"
    PRESTAINED = "PRESTAINED", "Prestained"
    DUAL_COLOR = "DUAL_COLOR", "Dual Color"
    BROAD_RANGE = "BROAD_RANGE", "Broad Range"
    LOW_RANGE = "LOW_RANGE", "Low Range"
    HIGH_RANGE = "HIGH_RANGE", "High Range"


class BandColor(models.TextChoices):
    """Colors for prestained marker bands."""

    NONE = "NONE", "None (Unstained)"
    BLUE = "BLUE", "Blue"
    PINK = "PINK", "Pink"
    GREEN = "GREEN", "Green"
    ORANGE = "ORANGE", "Orange"
    RED = "RED", "Red"
    YELLOW = "YELLOW", "Yellow"
    PURPLE = "PURPLE", "Purple"


class CalibrationMethod(models.TextChoices):
    """Regression methods for MW calibration."""

    LOG_LINEAR = "LOG_LINEAR", "Log-Linear (log10MW = a*Rf + b)"
    POLYNOMIAL_2 = "POLYNOMIAL_2", "Quadratic Polynomial"
    POLYNOMIAL_3 = "POLYNOMIAL_3", "Cubic Polynomial"


class InterpolationMethod(models.TextChoices):
    """Interpolation methods for multi-ladder calibration."""

    LINEAR = "LINEAR", "Linear (distance-weighted)"
    NEAREST = "NEAREST", "Nearest ladder only"


class LadderTemplate(models.Model):
    """
    Reusable MW ladder definition for calibration.

    A template defines the known molecular weights for a commercial or custom
    MW ladder. Users can select a template when calibrating their gel analysis.

    Global templates (is_global=True) are shared across all users and seeded
    via management command. Users can also create their own templates.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Identity
    name = models.CharField(
        max_length=255,
        help_text="Display name (e.g., 'Precision Plus Protein Unstained')",
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique code for programmatic reference (e.g., 'PRECISION_PLUS_UNSTAINED')",
    )
    manufacturer = models.CharField(
        max_length=100,
        help_text="Manufacturer name (e.g., 'Bio-Rad')",
    )
    catalog_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Product catalog number",
    )
    category = models.CharField(
        max_length=20,
        choices=LadderCategory.choices,
        default=LadderCategory.UNSTAINED,
    )
    description = models.TextField(
        blank=True,
        help_text="Additional notes about this ladder",
    )

    # Computed fields (auto-updated on band save)
    band_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of bands in this ladder (auto-calculated)",
    )
    mw_range_min = models.FloatField(
        null=True,
        blank=True,
        help_text="Minimum MW in kDa (auto-calculated)",
    )
    mw_range_max = models.FloatField(
        null=True,
        blank=True,
        help_text="Maximum MW in kDa (auto-calculated)",
    )

    # Permissions
    is_global = models.BooleanField(
        default=False,
        help_text="Global templates are shared across all users",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive templates are hidden from selection",
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ladder_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(
        history_change_reason_field=models.TextField(null=True),
    )

    class Meta:
        ordering = ["manufacturer", "name"]
        verbose_name = "Ladder Template"
        verbose_name_plural = "06. Ladder Templates"

    def __str__(self):
        return f"{self.name} ({self.manufacturer})"

    def update_computed_fields(self):
        """Recalculate band_count and MW range from bands."""
        bands = self.bands.all()
        self.band_count = bands.count()
        if bands.exists():
            agg = bands.aggregate(
                min_mw=Min("mw_kda"),
                max_mw=Max("mw_kda"),
            )
            self.mw_range_min = agg["min_mw"]
            self.mw_range_max = agg["max_mw"]
        else:
            self.mw_range_min = None
            self.mw_range_max = None
        self.save(update_fields=["band_count", "mw_range_min", "mw_range_max"])

    @property
    def mw_range_display(self) -> str:
        """Display MW range as string."""
        if self.mw_range_min and self.mw_range_max:
            return f"{self.mw_range_min:.0f}-{self.mw_range_max:.0f} kDa"
        return "N/A"


class LadderBandDefinition(models.Model):
    """
    Individual band in a ladder template.

    Each band has a known molecular weight. Bands are ordered from top
    (highest MW, band_order=1) to bottom (lowest MW).
    """

    template = models.ForeignKey(
        LadderTemplate,
        on_delete=models.CASCADE,
        related_name="bands",
    )

    # Band properties
    mw_kda = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="Known molecular weight in kDa",
    )
    band_order = models.PositiveSmallIntegerField(
        help_text="Order from top (1=highest MW) to bottom",
    )

    # Optional properties for matching algorithms
    relative_intensity = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Relative intensity 0-1 for matching algorithm",
    )
    is_reference_band = models.BooleanField(
        default=False,
        help_text="Mark bright reference bands for easier identification",
    )
    color = models.CharField(
        max_length=20,
        choices=BandColor.choices,
        default=BandColor.NONE,
        help_text="Band color for prestained markers",
    )

    # Learned pattern data (from training calibrations)
    expected_rf = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Expected relative migration (Rf) position (0=well, 1=front)",
    )
    expected_rf_tolerance = models.FloatField(
        default=0.05,
        validators=[MinValueValidator(0.01), MaxValueValidator(0.2)],
        help_text="Allowed Rf deviation for matching",
    )
    intensity_rank = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Intensity rank (1=brightest) for pattern validation",
    )

    class Meta:
        ordering = ["template", "band_order"]
        unique_together = [
            ["template", "band_order"],
            ["template", "mw_kda"],
        ]
        verbose_name = "Ladder Band"
        verbose_name_plural = "Ladder Bands"

    def __str__(self):
        return f"{self.mw_kda} kDa (#{self.band_order})"

    def save(self, *args, **kwargs):
        """Update template computed fields after save."""
        super().save(*args, **kwargs)
        # Update parent template's computed fields
        self.template.update_computed_fields()

    def delete(self, *args, **kwargs):
        """Update template computed fields after delete."""
        template = self.template
        super().delete(*args, **kwargs)
        template.update_computed_fields()


class LadderCalibration(models.Model):
    """
    Calibration result for a specific ladder lane in a gel analysis.

    Links a GelAnalysis to a LadderTemplate and stores the computed
    calibration curve coefficients for MW estimation.

    Multiple calibrations per analysis are supported for gel smile correction
    using position-aware interpolation between ladder lanes.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Links - ForeignKey allows multiple calibrations per analysis
    analysis = models.ForeignKey(
        "gel_analyzer.GelAnalysis",
        on_delete=models.CASCADE,
        related_name="ladder_calibrations",
    )
    ladder_lane = models.ForeignKey(
        "gel_analyzer.Lane",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"lane_type": "LADDER"},
        related_name="calibrations",
        help_text="The ladder lane used for calibration",
    )
    template = models.ForeignKey(
        LadderTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calibrations",
        help_text="The ladder template used for MW values",
    )

    # Position for interpolation - cached for query efficiency
    ladder_x_position = models.PositiveIntegerField(
        default=0,
        help_text="X center of ladder lane (x + width/2) for position-aware interpolation",
    )

    # Calibration results
    method = models.CharField(
        max_length=20,
        choices=CalibrationMethod.choices,
        default=CalibrationMethod.LOG_LINEAR,
    )
    coefficients = models.JSONField(
        default=dict,
        help_text="Regression coefficients: {slope, intercept} or {coeffs: [...]}",
    )
    r_squared = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Coefficient of determination (R^2)",
    )

    # Matching details
    matched_band_count = models.PositiveSmallIntegerField(
        help_text="Number of bands successfully matched",
    )
    band_matches = models.JSONField(
        default=list,
        help_text="Band match details: [{band_id, mw_kda, position_y, rf, residual}, ...]",
    )
    excluded_band_ids = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of ladder band UUIDs the user excluded from this fit. Persisted "
            "so a re-open of the calibration modal restores the same selection."
        ),
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_calibrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["analysis", "ladder_x_position"]
        verbose_name = "Ladder Calibration"
        verbose_name_plural = "07. Ladder Calibrations"
        constraints = [
            models.UniqueConstraint(
                fields=["analysis", "ladder_lane"],
                name="unique_calibration_per_ladder_lane",
            ),
        ]

    def __str__(self):
        template_name = self.template.name if self.template else "Unknown"
        return f"Calibration for {self.analysis} using {template_name}"

    @property
    def r_squared_quality(self) -> str:
        """Return quality indicator based on R^2 value."""
        if self.r_squared >= 0.99:
            return "excellent"
        elif self.r_squared >= 0.95:
            return "good"
        elif self.r_squared >= 0.90:
            return "acceptable"
        else:
            return "poor"

    @property
    def equation_display(self) -> str:
        """Return human-readable equation."""
        if self.method == CalibrationMethod.LOG_LINEAR:
            slope = self.coefficients.get("slope", 0)
            intercept = self.coefficients.get("intercept", 0)
            return f"log10(MW) = {slope:.4f} * Rf + {intercept:.4f}"
        elif self.method in (CalibrationMethod.POLYNOMIAL_2, CalibrationMethod.POLYNOMIAL_3):
            coeffs = self.coefficients.get("coeffs", [])
            if not coeffs:
                return "N/A"
            # Build polynomial equation string
            terms = []
            degree = len(coeffs) - 1
            for i, c in enumerate(coeffs):
                power = degree - i
                if power == 0:
                    terms.append(f"{c:.4f}")
                elif power == 1:
                    terms.append(f"{c:.4f}*Rf")
                else:
                    terms.append(f"{c:.4f}*Rf^{power}")
            return f"log10(MW) = {' + '.join(terms)}"
        return "N/A"

    def estimate_mw(self, position_y: int, lane_top: int, lane_bottom: int) -> float | None:
        """
        Calculate MW from Y position using calibration curve.

        Args:
            position_y: Y position of band in pixels (from top of image)
            lane_top: Y position of lane top (well)
            lane_bottom: Y position of lane bottom (dye front)

        Returns:
            Estimated molecular weight in kDa, or None if calculation fails
        """
        if lane_bottom <= lane_top:
            return None

        # Calculate relative migration (Rf)
        # Rf = 0 at well (lane_top), Rf = 1 at dye front (lane_bottom)
        rf = (position_y - lane_top) / (lane_bottom - lane_top)

        # Clamp Rf to valid range
        rf = max(0.0, min(1.0, rf))

        try:
            if self.method == CalibrationMethod.LOG_LINEAR:
                slope = self.coefficients.get("slope", 0)
                intercept = self.coefficients.get("intercept", 0)
                log_mw = slope * rf + intercept
                return 10**log_mw

            elif self.method in (CalibrationMethod.POLYNOMIAL_2, CalibrationMethod.POLYNOMIAL_3):
                coeffs = self.coefficients.get("coeffs", [])
                if not coeffs:
                    return None
                # Evaluate polynomial: coeffs[0]*x^n + coeffs[1]*x^(n-1) + ... + coeffs[n]
                log_mw = sum(c * (rf ** (len(coeffs) - 1 - i)) for i, c in enumerate(coeffs))
                return 10**log_mw

        except (ValueError, OverflowError, ZeroDivisionError):
            return None

        return None

    def save(self, *args, **kwargs):
        """Auto-populate ladder_x_position from lane geometry before save."""
        if self.ladder_lane and not self.ladder_x_position:
            # Calculate center X position from lane geometry
            self.ladder_x_position = self.ladder_lane.x + (self.ladder_lane.width // 2)
        super().save(*args, **kwargs)


class MultiLadderCalibrationConfig(models.Model):
    """
    Analysis-level configuration for multi-ladder calibration.

    Stores the shared template and interpolation method for all ladder
    calibrations in an analysis. This enables gel smile correction by
    interpolating MW estimates between multiple ladder lanes.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    analysis = models.OneToOneField(
        "gel_analyzer.GelAnalysis",
        on_delete=models.CASCADE,
        related_name="multi_ladder_config",
    )
    template = models.ForeignKey(
        LadderTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="multi_ladder_configs",
        help_text="Same template used for all ladder lanes",
    )
    interpolation_method = models.CharField(
        max_length=20,
        choices=InterpolationMethod.choices,
        default=InterpolationMethod.LINEAR,
        help_text="Method for interpolating MW between ladder lanes",
    )

    # Status
    is_calibrated = models.BooleanField(
        default=False,
        help_text="True when all ladder lanes have been successfully calibrated",
    )
    ladder_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of calibrated ladder lanes",
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_multi_ladder_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Multi-Ladder Calibration Config"
        verbose_name_plural = "08. Multi-Ladder Calibration Configs"

    def __str__(self):
        template_name = self.template.name if self.template else "No template"
        return f"Multi-ladder config for {self.analysis}: {template_name} ({self.ladder_count} ladders)"

    def update_status(self):
        """Update calibration status from related calibrations."""
        calibrations = self.analysis.ladder_calibrations.all()
        self.ladder_count = calibrations.count()
        self.is_calibrated = self.ladder_count > 0
        self.save(update_fields=["ladder_count", "is_calibrated", "updated_at"])
