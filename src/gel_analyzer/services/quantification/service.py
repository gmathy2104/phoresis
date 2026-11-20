"""ProteinQuantCalibrationService — fits a curve from CALIBRATION-tagged points
and projects samples onto it. Mirror of CalibrationService for protein quantification."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from django.db.models import Q

from phoresis_core.logging_config import get_logger

from . import fitters
from .models import QuantParams, QuantPoint, QuantResult

if TYPE_CHECKING:
    from gel_analyzer.models import Band, GelAnalysis, ProteinQuantCalibration

logger = get_logger(__name__)

# The bands `apply_to_analysis` projects -- its writer's scope: those of SAMPLE and CONTROL lanes, every band type
# but MW_REFERENCE (Lane.LaneType / Band.BandType values). Named so the gel export publishes a stored estimate only
# for a band this writer projects (gel_analyzer/api/export/rows.py).
PROJECTED_LANE_TYPES = ("SAMPLE", "CONTROL")
UNPROJECTED_BAND_TYPES = ("MW_REFERENCE",)


def quant_result_of(calibration: ProteinQuantCalibration) -> QuantResult:
    """The fit a stored calibration projects with -- what :meth:`apply_to_analysis` rebuilds, nothing else."""
    return QuantResult(
        success=True,
        method=calibration.method,
        unit=calibration.unit,
        coefficients=calibration.coefficients,
        r_squared=calibration.r_squared,
        equation=calibration.equation,
    )


def calibration_point_bands_q() -> Q:
    """The bands a calibration is fitted on: CALIBRATION bands with a declared load, in CALIBRATION lanes.

    A ``Band`` filter, shared by :meth:`ProteinQuantCalibrationService.collect_calibration_points` and the gel
    export's ``estimate_within_calibration_range`` (``gel_analyzer/api/export/rows.py``): one set of points.
    """
    from gel_analyzer.models import Band, Lane

    return Q(lane__lane_type=Lane.LaneType.CALIBRATION, band_type=Band.BandType.CALIBRATION, quant_point__isnull=False)


# ------------ Calibration range ------------------------------------------------
# A projection outside the standards' areas is an extrapolation: kept, never refused, but flagged -- a poly2 or a
# 4PL can turn sharply past its last point. ONE rule for every reader: the stored DensitometryResult.
# estimated_amount_range (apply_to_analysis), the preview's projections, the report, the gel export's
# estimate_within_calibration_range.


def calibration_area_span(points, excluded_band_ids) -> tuple[float, float] | None:
    """[min, max] corrected area of a fit's standards -- ``(band id, area)`` pairs (the bands of
    :func:`calibration_point_bands_q`) minus ``excluded_band_ids``, what :meth:`ProteinQuantCalibrationService.fit`
    leaves out. A standard without an area is skipped; None when none holds one."""
    excluded = {str(band_id) for band_id in excluded_band_ids or []}
    areas = [area for band_id, area in points if area is not None and str(band_id) not in excluded]
    return (min(areas), max(areas)) if areas else None


def calibration_range_of(area: float | None, span: tuple[float, float] | None) -> str | None:
    """The ``DensitometryResult.CalibrationRange`` value of ``area`` against ``span``, bounds inclusive; None
    without both, or when a NaN is involved (it compares neither below nor above: it would read as in range)."""
    from gel_analyzer.models import DensitometryResult

    if area is None or span is None or any(math.isnan(value) for value in (area, *span)):
        return None
    if area < span[0]:
        return DensitometryResult.CalibrationRange.BELOW_RANGE.value
    if area > span[1]:
        return DensitometryResult.CalibrationRange.ABOVE_RANGE.value
    return DensitometryResult.CalibrationRange.IN_RANGE.value


class ProteinQuantCalibrationService:
    def __init__(self, params: QuantParams | None = None):
        self.params = params or QuantParams()

    # ------------ Collection -------------------------------------------------

    def collect_calibration_points(self, analysis: GelAnalysis) -> list[QuantPoint]:
        """All CALIBRATION-typed bands inside CALIBRATION-typed lanes of the analysis."""
        from gel_analyzer.models import Band

        bands = (
            Band.objects.filter(calibration_point_bands_q(), lane__analysis=analysis)
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
        """POI bands of SAMPLE lanes; corrected_area is None if densitometry has
        not been run for the band.

        Used to be "all non-MW_REFERENCE bands" but that flooded the
        quantification modal's "Samples projected" table (and the curve
        plot) with every contaminant / OTHER band the user had drawn on
        a sample lane. The user explicitly asked to show only POI here
        — those are the bands we actually quantify. OTHER / CALIBRATION
        bands on a SAMPLE lane shouldn't drive a projection: OTHER is
        noise we don't care to quantify, and CALIBRATION points belong
        to a CALIBRATION lane post-auto-promote (see
        band_type_change.apply_band_type)."""
        from gel_analyzer.models import Band, Lane

        bands = (
            Band.objects.filter(
                lane__analysis=analysis,
                lane__lane_type=Lane.LaneType.SAMPLE,
                band_type=Band.BandType.POI,
            )
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
            role="SAMPLE",
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
                success=False,
                method=self.params.method,
                unit=self.params.unit,
                error_message=f"Densitometry missing on {len(missing)} band(s); run densitometry first",
                calibration_points=points,
            )
        if len(non_excluded) < 2:
            return QuantResult(
                success=False,
                method=self.params.method,
                unit=self.params.unit,
                error_message=f"Need at least 2 non-excluded points, got {len(non_excluded)}",
                calibration_points=points,
            )
        if self.params.method == "FOUR_PL" and len(non_excluded) < 4:
            return QuantResult(
                success=False,
                method=self.params.method,
                unit=self.params.unit,
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
                success=False,
                method=self.params.method,
                unit=self.params.unit,
                error_message=str(e),
                calibration_points=points,
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

    # ------------ Projection / persistence -----------------------------------

    def project(self, area: float, result: QuantResult) -> float | None:
        """Forward-evaluate the fit at x=area to obtain the predicted amount."""
        if not result.success or area is None:
            return None
        if result.method == "LINEAR":
            return fitters.predict_linear(result.coefficients, area)
        if result.method == "POLYNOMIAL_2":
            # Fit was amounts = f(areas), so to predict amount we evaluate the polynomial
            # forward (not inverse). Override the call accordingly.
            coeffs = result.coefficients["coeffs"]
            return float(np.polyval(coeffs, area))
        if result.method == "FOUR_PL":
            # Same: 4PL was fit as amount = f(area). Forward evaluation:
            a = result.coefficients["a"]
            d = result.coefficients["d"]
            c = result.coefficients["c"]
            b = result.coefficients["b"]
            return float(d + (a - d) / (1 + (area / c) ** b))
        return None

    def apply_to_analysis(self, calibration: ProteinQuantCalibration) -> int:
        """Persist DensitometryResult.estimated_amount{,_unit,_range} for all SAMPLE/CONTROL
        bands of the calibration's analysis. Returns count of rows updated."""
        from gel_analyzer.models import Band, DensitometryResult

        result = quant_result_of(calibration)
        span = calibration_area_span(
            ((p.band_id, p.corrected_area) for p in self.collect_calibration_points(calibration.analysis)),
            calibration.excluded_band_ids,
        )
        target_bands = (
            Band.objects.filter(
                lane__analysis=calibration.analysis,
                lane__lane_type__in=PROJECTED_LANE_TYPES,
                densitometry__isnull=False,
            )
            .exclude(band_type__in=UNPROJECTED_BAND_TYPES)
            .select_related("densitometry", "lane")
        )
        updated = 0
        skipped_negative = 0
        outside = 0
        for band in target_bands:
            estimated = self.project(band.densitometry.corrected_area, result)
            if estimated is None:
                continue
            if estimated < 0:
                # Bands whose corrected_area lies outside the calibration domain
                # extrapolate to a negative amount. Surface at debug level so a
                # report run with many missing values can be traced back here.
                logger.debug(
                    f"Quantification: skipped negative projection for band {band.id} "
                    f"(area={band.densitometry.corrected_area:.2f} → {estimated:.4f})"
                )
                skipped_negative += 1
                continue
            calibration_range = calibration_range_of(band.densitometry.corrected_area, span)
            DensitometryResult.objects.filter(pk=band.densitometry.pk).update(
                estimated_amount=float(estimated),
                estimated_amount_unit=calibration.unit,
                estimated_amount_range=calibration_range,
            )
            updated += 1
            if calibration_range not in (None, DensitometryResult.CalibrationRange.IN_RANGE):
                outside += 1
        logger.info(
            f"Quantification calibration {calibration.id} applied to {updated} bands "
            f"({skipped_negative} skipped as negative extrapolations, {outside} outside the calibration range)"
        )
        return updated

    def save_active(
        self,
        analysis: GelAnalysis,
        result: QuantResult,
        *,
        user=None,
        notes: str = "",
    ) -> ProteinQuantCalibration:
        from django.db import transaction
        from django.utils import timezone

        from gel_analyzer.models import ProteinQuantCalibration
        from gel_analyzer.services.analysis_status import refuse_if_final

        if not result.success:
            raise ValueError(f"Cannot save a failed fit: {result.error_message}")

        with transaction.atomic():
            # An approved analysis is final (services/analysis_status.py): read under the row lock,
            # so an approval and a save are ordered. Raises AnalysisIsFinal; nothing is written.
            refuse_if_final(analysis.pk, lock=True)
            previous = analysis.quant_calibrations.filter(is_active=True)
            previous.update(is_active=False, superseded_at=timezone.now())
            calib = ProteinQuantCalibration.objects.create(
                analysis=analysis,
                method=result.method,
                unit=result.unit,
                coefficients=result.coefficients,
                r_squared=result.r_squared,
                equation=result.equation,
                excluded_band_ids=[p.band_id for p in result.calibration_points if p.is_excluded],
                is_active=True,
                created_by=user,
                notes=notes,
            )
        return calib
