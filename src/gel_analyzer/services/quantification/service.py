"""ProteinQuantCalibrationService — fits a curve from CALIBRATION-tagged points
and projects samples onto it. Mirror of CalibrationService for protein quantification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

from .models import QuantParams, QuantPoint

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
