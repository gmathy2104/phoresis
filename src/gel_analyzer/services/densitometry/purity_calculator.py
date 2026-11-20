"""
Purity calculator for POI (Protein of Interest) analysis.

Calculates purity metrics based on band classification:
- POI bands (target protein)
- OTHER bands (impurities, host cell proteins)
- MW_REFERENCE bands (ladder markers, excluded from purity)

Purity = POI_Area / (POI_Area + OTHER_Area) * 100%
"""

from __future__ import annotations

from phoresis_core.logging_config import get_logger

from .models import LaneDensitometryResultData, PeakIntegrationResult

logger = get_logger(__name__)


class PurityCalculator:
    """
    Calculate purity metrics for gel analysis.

    Purity is defined as the percentage of target protein (POI)
    relative to total sample protein (excluding MW reference markers).

    Usage:
        calculator = PurityCalculator()
        purity = calculator.calculate_lane_purity(peaks)
    """

    def calculate_lane_purity(
        self,
        peaks: list[PeakIntegrationResult],
        exclude_reference: bool = True,
    ) -> float | None:
        """
        Calculate purity percentage for a lane.

        Purity = POI / (POI + OTHER) * 100

        Args:
            peaks: List of peak integration results.
            exclude_reference: Whether to exclude MW_REFERENCE bands.

        Returns:
            Purity percentage (0-100) or None if no POI bands.
        """
        if not peaks:
            return None

        # Separate by band type
        poi_area = 0.0
        other_area = 0.0

        for peak in peaks:
            area = peak.corrected_area
            if area <= 0:
                continue

            if peak.band_type == "POI":
                poi_area += area
            elif peak.band_type == "OTHER" or peak.band_type == "MW_REFERENCE" and not exclude_reference:
                other_area += area

        if poi_area <= 0:
            # No POI bands, cannot compute purity
            return None

        total_sample = poi_area + other_area
        if total_sample <= 0:
            return None

        purity = (poi_area / total_sample) * 100.0

        logger.debug(f"Purity calculation: POI={poi_area:.1f}, OTHER={other_area:.1f}, purity={purity:.2f}%")

        return purity

    def calculate_relative_abundance(
        self,
        peaks: list[PeakIntegrationResult],
        reference_band_type: str = "MW_REFERENCE",
    ) -> dict[str, float | None]:
        """
        Calculate relative abundance of POI and OTHER vs reference.

        Useful for comparing across lanes with different loading amounts.

        Args:
            peaks: List of peak integration results.
            reference_band_type: Band type to use as reference.

        Returns:
            Dict with poi_relative, other_relative (relative to reference).
        """
        reference_area = sum(
            p.corrected_area for p in peaks if p.band_type == reference_band_type and p.corrected_area > 0
        )

        if reference_area <= 0:
            return {
                "poi_relative": None,
                "other_relative": None,
                "reference_area": 0.0,
            }

        poi_area = sum(p.corrected_area for p in peaks if p.band_type == "POI" and p.corrected_area > 0)

        other_area = sum(p.corrected_area for p in peaks if p.band_type == "OTHER" and p.corrected_area > 0)

        return {
            "poi_relative": (poi_area / reference_area) * 100.0 if poi_area > 0 else 0.0,
            "other_relative": (other_area / reference_area) * 100.0 if other_area > 0 else 0.0,
            "reference_area": reference_area,
        }

    def calculate_band_contribution(
        self,
        peak: PeakIntegrationResult,
        peaks: list[PeakIntegrationResult],
    ) -> float | None:
        """
        Calculate a band's contribution to total sample area.

        Args:
            peak: The specific peak to calculate contribution for.
            peaks: All peaks in the lane.

        Returns:
            Contribution percentage (0-100) or None.
        """
        total = sum(p.corrected_area for p in peaks if p.corrected_area > 0 and p.band_type != "MW_REFERENCE")

        if total <= 0:
            return None

        if peak.corrected_area <= 0:
            return 0.0

        return (peak.corrected_area / total) * 100.0

    def get_purity_summary(
        self,
        lane_result: LaneDensitometryResultData,
    ) -> dict:
        """
        Get comprehensive purity summary for a lane.

        Args:
            lane_result: Lane densitometry result.

        Returns:
            Dict with purity metrics.
        """
        if not lane_result.peaks:
            return {
                "purity": None,
                "poi_area": 0.0,
                "other_area": 0.0,
                "reference_area": 0.0,
                "total_sample_area": 0.0,
                "poi_band_count": 0,
                "other_band_count": 0,
            }

        peaks = lane_result.peaks

        poi_peaks = [p for p in peaks if p.band_type == "POI" and p.corrected_area > 0]
        other_peaks = [p for p in peaks if p.band_type == "OTHER" and p.corrected_area > 0]
        ref_peaks = [p for p in peaks if p.band_type == "MW_REFERENCE" and p.corrected_area > 0]

        poi_area = sum(p.corrected_area for p in poi_peaks)
        other_area = sum(p.corrected_area for p in other_peaks)
        ref_area = sum(p.corrected_area for p in ref_peaks)

        total_sample = poi_area + other_area

        purity = None
        if poi_area > 0 and total_sample > 0:
            purity = (poi_area / total_sample) * 100.0

        return {
            "purity": purity,
            "poi_area": poi_area,
            "other_area": other_area,
            "reference_area": ref_area,
            "total_sample_area": total_sample,
            "poi_band_count": len(poi_peaks),
            "other_band_count": len(other_peaks),
            "reference_band_count": len(ref_peaks),
        }
