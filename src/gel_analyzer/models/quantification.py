"""Protein quantification models — one ProteinQuantCalibration per analysis +
calibration / control points anchored on Band rows."""

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class ProteinQuantCalibrationPoint(models.Model):
    """A single calibration or control point — load amount declared by the user
    on a CALIBRATION-typed Band. The calibration role is derived from the parent
    lane's type (CALIBRATION vs CONTROL) and persisted for audit."""

    UNIT_UG = "UG"
    UNIT_UG_ML = "UG_ML"
    UNIT_CHOICES = [(UNIT_UG, "µg"), (UNIT_UG_ML, "µg/mL")]

    ROLE_CALIBRATION = "CALIBRATION"
    ROLE_CONTROL = "CONTROL"
    ROLE_CHOICES = [(ROLE_CALIBRATION, "Calibration"), (ROLE_CONTROL, "Control")]

    band = models.OneToOneField(
        "Band",
        on_delete=models.CASCADE,
        related_name="quant_point",
        limit_choices_to={"band_type": "CALIBRATION"},
    )
    load_amount = models.FloatField(validators=[MinValueValidator(0)])
    load_unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    is_excluded_from_fit = models.BooleanField(default=False)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CALIBRATION,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quantification Point"
        verbose_name_plural = "09. Quantification Points"
        indexes = [models.Index(fields=["role"])]

    def __str__(self) -> str:
        return f"{self.role} point: {self.load_amount} {self.load_unit}"


class ProteinQuantCalibration(models.Model):
    """One active protein quantification calibration per analysis. Older fits are
    kept with is_active=False, superseded_at=now() for audit."""

    METHOD_LINEAR = "LINEAR"
    METHOD_POLY2 = "POLYNOMIAL_2"
    METHOD_4PL = "FOUR_PL"
    METHOD_CHOICES = [
        (METHOD_LINEAR, "Linear"),
        (METHOD_POLY2, "Polynomial (deg 2)"),
        (METHOD_4PL, "4-Parameter Logistic"),
    ]

    UNIT_UG = "UG"
    UNIT_UG_ML = "UG_ML"
    UNIT_CHOICES = [(UNIT_UG, "µg"), (UNIT_UG_ML, "µg/mL")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey("GelAnalysis", on_delete=models.CASCADE, related_name="quant_calibrations")
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    coefficients = models.JSONField()
    r_squared = models.FloatField()
    equation = models.CharField(max_length=255)
    excluded_band_ids = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    # Last time invalidation.recompute_if_active mutated this row's coefficients
    # in response to upstream densitometry changes. Stays None for the row
    # exactly as it was created by the user; ticks every time a background
    # refit shifts the fit. Distinguishes user-saved state from drift.
    last_recomputed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_quant_calibrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Protein Quantification Calibration"
        verbose_name_plural = "10. Protein Quantification Calibrations"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["analysis"],
                condition=models.Q(is_active=True),
                name="uniq_active_quant_calibration_per_analysis",
            ),
        ]
        indexes = [models.Index(fields=["analysis", "is_active"])]

    def __str__(self) -> str:
        flag = "active" if self.is_active else "superseded"
        return f"{self.method} calib ({flag}) — analysis {self.analysis_id}"
