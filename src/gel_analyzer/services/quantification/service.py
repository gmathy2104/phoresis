"""ProteinQuantCalibrationService — fits a curve from CALIBRATION-tagged points
and projects samples onto it. Mirror of CalibrationService for protein quantification."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from phoresis_core.logging_config import get_logger

from . import fitters
from .models import QuantParams, QuantPoint, QuantResult

if TYPE_CHECKING:
    from gel_analyzer.models import Band, GelAnalysis

logger = get_logger(__name__)


class ProteinQuantCalibrationService:
    def __init__(self, params: QuantParams | None = None):
        self.params = params or QuantParams()

    # ------------ Collection -------------------------------------------------

    def collect_calibration_points(self, analysis: GelAnalysis) -> list[QuantPoint]:
        """All CALIBRATION-typed bands inside CALIBRATION-typed lanes of the analysis."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.CALIBRATION,
                band_type=Band.BandType.CALIBRATION,
                quant_point__isnull=False,
            )
            .select_related("lane", "quant_point")
            .prefetch_related("densitometry")
        )
        return [self._band_to_point(b, role="CALIBRATION") for b in bands]

    def collect_control_points(self, analysis: GelAnalysis) -> list[QuantPoint]:
        """All CALIBRATION-typed bands inside CONTROL-typed lanes."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.CONTROL,
                band_type=Band.BandType.CALIBRATION,
                quant_point__isnull=False,
            )
            .select_related("lane", "quant_point")
            .prefetch_related("densitometry")
        )
        return [self._band_to_point(b, role="CONTROL") for b in bands]

    def collect_sample_bands(self, analysis: GelAnalysis) -> list[QuantPoint]:
        """All non-MW_REFERENCE bands of SAMPLE lanes that have densitometry."""
        from gel_analyzer.models import Band, Lane
        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.SAMPLE,
            )
            .exclude(band_type=Band.BandType.MW_REFERENCE)
            .select_related("lane")
            .prefetch_related("densitometry")
        )
        return [self._band_to_sample_point(b) for b in bands]

    @staticmethod
    def _band_to_point(band: Band, *, role: str) -> QuantPoint:
        densito = getattr(band, "densitometry", None)
        qp = band.quant_point
        return QuantPoint(
            band_id=str(band.id),
            lane_id=band.lane_id,
            lane_number=band.lane.lane_number,
            role=role,
            load_amount=qp.load_amount,
            load_unit=qp.load_unit,
            corrected_area=densito.corrected_area if densito else None,
            is_excluded=qp.is_excluded_from_fit,
        )

    @staticmethod
    def _band_to_sample_point(band: Band) -> QuantPoint:
        densito = getattr(band, "densitometry", None)
        return QuantPoint(
            band_id=str(band.id),
            lane_id=band.lane_id,
            lane_number=band.lane.lane_number,
            role="CALIBRATION",  # placeholder; sample projections don't carry roles
            load_amount=None,
            load_unit=None,
            corrected_area=densito.corrected_area if densito else None,
        )

    # ------------ Fit --------------------------------------------------------

    def fit(
        self,
        points: list[QuantPoint],
        excluded_band_ids: list[str] | None = None,
    ) -> QuantResult:
        excluded = set(excluded_band_ids or [])
        for p in points:
            p.is_excluded = p.band_id in excluded
        non_excluded = [p for p in points if not p.is_excluded]
        missing = [p.band_id for p in non_excluded if p.corrected_area is None]
        if missing:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"Densitometry missing on {len(missing)} band(s); run densitometry first",
                calibration_points=points,
            )
        if len(non_excluded) < 2:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"Need at least 2 non-excluded points, got {len(non_excluded)}",
                calibration_points=points,
            )
        if self.params.method == "FOUR_PL" and len(non_excluded) < 4:
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=f"4PL requires at least 4 non-excluded points, got {len(non_excluded)}",
                calibration_points=points,
            )

        areas = np.array([p.corrected_area for p in non_excluded], dtype=float)
        amounts = np.array([p.load_amount for p in non_excluded], dtype=float)

        try:
            if self.params.method == "LINEAR":
                coeffs, r2, residuals = fitters.fit_linear(areas, amounts)
                eq = fitters.linear_equation(coeffs, self.params.unit)
            elif self.params.method == "POLYNOMIAL_2":
                coeffs, r2, residuals = fitters.fit_poly2(areas, amounts)
                eq = fitters.poly2_equation(coeffs, self.params.unit)
            elif self.params.method == "FOUR_PL":
                coeffs, r2, residuals = fitters.fit_4pl(areas, amounts)
                eq = fitters.four_pl_equation(coeffs, self.params.unit)
            else:
                return QuantResult(
                    success=False,
                    error_message=f"Unknown method: {self.params.method}",
                    calibration_points=points,
                )
        except Exception as e:
            logger.error(f"Quantification fit failed: {e}")
            return QuantResult(
                success=False, method=self.params.method, unit=self.params.unit,
                error_message=str(e), calibration_points=points,
            )

        # residuals = observed - predicted, so predicted = observed - residual
        for p, r in zip(non_excluded, residuals, strict=False):
            p.residual = float(r)
            p.predicted_amount = float(p.load_amount - r)

        return QuantResult(
            success=True,
            method=self.params.method,
            unit=self.params.unit,
            coefficients=coeffs,
            r_squared=r2,
            equation=eq,
            calibration_points=points,
        )
