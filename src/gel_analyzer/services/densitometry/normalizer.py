"""
Densitometry normalizer for relative quantification.

Provides multiple normalization methods:
- LANE_TOTAL: Normalize to total band area within each lane
- GEL_TOTAL: Normalize to total band area across entire gel
- LOADING_CONTROL: Normalize to a specific band type (e.g., housekeeping protein)
- REFERENCE_BAND: Normalize to a specific reference band
"""

from __future__ import annotations

from phoresis_core.logging_config import get_logger

from .models import (
    DensitometryParams,
    LaneDensitometryResultData,
    NormalizationMethod,
)

logger = get_logger(__name__)


class DensitometryNormalizer:
    """
    Normalize densitometry results for relative quantification.

    Computes relative percentages for bands based on the configured
    normalization method (lane total, gel total, loading control, etc.).

    Usage:
        normalizer = DensitometryNormalizer(params)
        normalizer.normalize_lane(lane_result)
        normalizer.normalize_gel(lane_results)
    """

    def __init__(self, params: DensitometryParams):
        """
        Initialize normalizer with parameters.

        Args:
            params: Densitometry parameters including normalization method.
        """
        self.params = params

    def normalize_lane(
        self,
        lane_result: LaneDensitometryResultData,
        reference_area: float | None = None,
    ) -> LaneDensitometryResultData:
        """
        Normalize bands within a single lane.

        Computes relative_percent_lane for each band based on the
        normalization method.

        Args:
            lane_result: Lane densitometry result with peak data.
            reference_area: Optional reference area for LOADING_CONTROL method.

        Returns:
            Updated LaneDensitometryResultData with normalized values.
        """
        if not lane_result.peaks:
            return lane_result

        method = self.params.normalization_method

        if method == NormalizationMethod.LANE_TOTAL:
            self._normalize_by_lane_total(lane_result)
        elif method == NormalizationMethod.LOADING_CONTROL:
            self._normalize_by_loading_control(lane_result, reference_area)
        elif method == NormalizationMethod.REFERENCE_BAND:
            self._normalize_by_reference_band(lane_result)
        else:
            # Default to lane total
            self._normalize_by_lane_total(lane_result)

        # Compute lane-level aggregations
        self._compute_lane_aggregations(lane_result)

        return lane_result

    def normalize_gel(
        self,
        lane_results: list[LaneDensitometryResultData],
    ) -> list[LaneDensitometryResultData]:
        """
        Normalize bands across all lanes in a gel.

        Computes relative_percent_gel for each band based on gel total.
        Also applies per-lane normalization if not GEL_TOTAL method.

        Args:
            lane_results: List of lane densitometry results.

        Returns:
            Updated list with gel-normalized values.
        """
        if not lane_results:
            return lane_results

        # First, compute lane-level normalization
        for lane_result in lane_results:
            self.normalize_lane(lane_result)

        # Compute gel total area
        gel_total = sum(lane.total_integrated_area for lane in lane_results if lane.success)

        if gel_total <= 0:
            logger.warning("Gel total area is zero, skipping gel normalization")
            return lane_results

        # Apply gel-level normalization
        for lane_result in lane_results:
            if not lane_result.success:
                continue

            for peak in lane_result.peaks:
                area = peak.corrected_area
                peak.relative_percent_gel = (area / gel_total) * 100.0

        logger.debug(f"Gel normalization complete: total area={gel_total:.1f}")

        return lane_results

    def _normalize_by_lane_total(
        self,
        lane_result: LaneDensitometryResultData,
    ) -> None:
        """
        Normalize by total area within the lane.

        Each band's percentage = (band area / lane total) * 100

        Args:
            lane_result: Lane result to normalize in-place.
        """
        # Compute total from corrected areas
        total_area = sum(p.corrected_area for p in lane_result.peaks if p.corrected_area > 0)

        if total_area <= 0:
            logger.warning(f"Lane {lane_result.lane_number}: zero total area")
            return

        # Count bands with zero or negative area for debugging
        skipped_bands = [p for p in lane_result.peaks if p.corrected_area <= 0]
        if skipped_bands:
            logger.debug(
                f"Lane {lane_result.lane_number}: {len(skipped_bands)} band(s) with "
                f"corrected_area <= 0 excluded from % calculation: "
                f"{[(p.band_id, p.band_type, p.corrected_area) for p in skipped_bands]}"
            )

        for peak in lane_result.peaks:
            if peak.corrected_area > 0:
                peak.relative_percent_lane = (peak.corrected_area / total_area) * 100.0
            else:
                peak.relative_percent_lane = 0.0

        lane_result.total_integrated_area = total_area

    def _normalize_by_loading_control(
        self,
        lane_result: LaneDensitometryResultData,
        reference_area: float | None = None,
    ) -> None:
        """
        Normalize by a loading control band.

        If reference_area is provided, use it. Otherwise, find bands
        with band_type='MW_REFERENCE' and use their total area.

        Args:
            lane_result: Lane result to normalize in-place.
            reference_area: Optional pre-computed reference area.
        """
        if reference_area is None:
            # Find loading control bands
            control_peaks = [p for p in lane_result.peaks if p.band_type == "MW_REFERENCE"]

            if control_peaks:
                reference_area = sum(p.corrected_area for p in control_peaks)
            else:
                # Fall back to lane total
                logger.warning(f"Lane {lane_result.lane_number}: no loading control found, falling back to lane total")
                self._normalize_by_lane_total(lane_result)
                return

        if reference_area <= 0:
            logger.warning(f"Lane {lane_result.lane_number}: zero reference area, falling back to lane total")
            self._normalize_by_lane_total(lane_result)
            return

        # Normalize relative to loading control
        for peak in lane_result.peaks:
            if peak.corrected_area > 0:
                peak.relative_percent_lane = (peak.corrected_area / reference_area) * 100.0
            else:
                peak.relative_percent_lane = 0.0

        # Lane total is still computed normally
        lane_result.total_integrated_area = sum(p.corrected_area for p in lane_result.peaks if p.corrected_area > 0)

    def _normalize_by_reference_band(
        self,
        lane_result: LaneDensitometryResultData,
    ) -> None:
        """
        Normalize by a specific reference band ID.

        Uses params.reference_band_id to identify the reference band.

        Args:
            lane_result: Lane result to normalize in-place.
        """
        reference_band_id = self.params.reference_band_id

        if not reference_band_id:
            logger.warning(
                f"Lane {lane_result.lane_number}: no reference band ID specified, falling back to lane total"
            )
            self._normalize_by_lane_total(lane_result)
            return

        # Find the reference band
        reference_peak = next((p for p in lane_result.peaks if p.band_id == reference_band_id), None)

        if reference_peak is None or reference_peak.corrected_area <= 0:
            logger.warning(
                f"Lane {lane_result.lane_number}: reference band {reference_band_id} "
                "not found or has zero area, falling back to lane total"
            )
            self._normalize_by_lane_total(lane_result)
            return

        reference_area = reference_peak.corrected_area

        # Normalize relative to reference band
        for peak in lane_result.peaks:
            if peak.corrected_area > 0:
                peak.relative_percent_lane = (peak.corrected_area / reference_area) * 100.0
            else:
                peak.relative_percent_lane = 0.0

        lane_result.total_integrated_area = sum(p.corrected_area for p in lane_result.peaks if p.corrected_area > 0)

    def _compute_lane_aggregations(
        self,
        lane_result: LaneDensitometryResultData,
    ) -> None:
        """
        Compute lane-level aggregations (POI area, purity, etc.).

        Args:
            lane_result: Lane result to update in-place.
        """
        # Separate peaks by type
        poi_peaks = [p for p in lane_result.peaks if p.band_type == "POI"]
        other_peaks = [p for p in lane_result.peaks if p.band_type == "OTHER"]
        ref_peaks = [p for p in lane_result.peaks if p.band_type == "MW_REFERENCE"]

        # Compute type-specific areas
        poi_area = sum(p.corrected_area for p in poi_peaks if p.corrected_area > 0)
        other_area = sum(p.corrected_area for p in other_peaks if p.corrected_area > 0)
        ref_area = sum(p.corrected_area for p in ref_peaks if p.corrected_area > 0)

        lane_result.poi_integrated_area = poi_area if poi_peaks else None
        lane_result.other_integrated_area = other_area if other_peaks else None
        lane_result.mw_reference_area = ref_area if ref_peaks else None

        # Compute purity (POI percentage)
        # Purity = POI / (POI + OTHER) * 100
        # Excludes MW_REFERENCE from the calculation
        sample_total = poi_area + other_area
        if sample_total > 0:
            # Always calculate purity when there are sample bands (POI or OTHER)
            lane_result.poi_percentage = (poi_area / sample_total) * 100.0
        else:
            # No sample bands at all (only MW_REFERENCE or nothing)
            lane_result.poi_percentage = None

        # Update band counts
        lane_result.bands_processed = len(lane_result.peaks)
        lane_result.bands_successful = sum(1 for p in lane_result.peaks if p.fit_successful or p.corrected_area > 0)


def compute_gel_statistics(
    lane_results: list[LaneDensitometryResultData],
) -> dict:
    """
    Compute gel-level statistics from lane results.

    Args:
        lane_results: List of lane densitometry results.

    Returns:
        Dictionary with gel statistics.
    """
    successful_lanes = [r for r in lane_results if r.success]

    if not successful_lanes:
        return {
            "gel_total_area": 0.0,
            "average_poi_percentage": None,
            "total_bands": 0,
            "total_poi_bands": 0,
        }

    gel_total = sum(r.total_integrated_area for r in successful_lanes)
    total_bands = sum(len(r.peaks) for r in successful_lanes)

    # Count POI bands
    total_poi_bands = sum(sum(1 for p in r.peaks if p.band_type == "POI") for r in successful_lanes)

    # Average purity across sample lanes
    sample_lanes = [r for r in successful_lanes if r.lane_type == "SAMPLE" and r.poi_percentage is not None]

    avg_purity = sum(r.poi_percentage for r in sample_lanes) / len(sample_lanes) if sample_lanes else None

    return {
        "gel_total_area": gel_total,
        "average_poi_percentage": avg_purity,
        "total_bands": total_bands,
        "total_poi_bands": total_poi_bands,
    }
