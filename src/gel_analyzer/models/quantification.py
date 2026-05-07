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
