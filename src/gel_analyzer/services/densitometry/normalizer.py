"""
Densitometry normalizer for relative quantification.

``relative_percent_lane`` follows the method asked for:
- LANE_TOTAL: each band as a share of its lane's total area
- LOADING_CONTROL: each band relative to its lane's MW_REFERENCE bands (the loading control)

``relative_percent_gel``, each band's share of the whole gel, is computed on every run.

A method never falls back to another (owner, 2026-10-05): Loading Control on a gel where a lane
with bands has no MW_REFERENCE band carrying signal is refused, for the whole gel, before anything is
normalised (``refuse_unless_normalizable``). It used to give that lane its lane total silently.
"""

from __future__ import annotations

from phoresis_core.logging_config import get_logger

from .models import DensitometryParams, LaneDensitometryResultData, NormalizationMethod

logger = get_logger(__name__)


class NormalizationRefused(ValueError):
    """The method asked for cannot normalise every lane: the run computes and saves nothing."""


class DensitometryNormalizer:
    """
    Normalize densitometry results for relative quantification.

    Computes relative percentages for bands based on the configured
    normalization method (lane total or loading control), and every band's share of the gel.

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
    ) -> LaneDensitometryResultData:
        """
        Normalize bands within a single lane.

        Computes relative_percent_lane for each band based on the
        normalization method.

        Args:
            lane_result: Lane densitometry result with peak data.

        Returns:
            Updated LaneDensitometryResultData with normalized values.

        Raises:
            NormalizationRefused: Loading Control on a lane without its reference.
        """
        if not lane_result.peaks:
            return lane_result

        if self.params.normalization_method == NormalizationMethod.LOADING_CONTROL:
            self._normalize_by_loading_control(lane_result)
        else:
            self._normalize_by_lane_total(lane_result)

        # Compute lane-level aggregations
        self._compute_lane_aggregations(lane_result)

        return lane_result

    def refuse_unless_normalizable(self, lane_results: list[LaneDensitometryResultData]) -> None:
        """
        Refuse the run when the method asked for cannot normalise every lane with bands.

        Loading Control divides each band by its lane's MW_REFERENCE bands, so every lane with bands
        needs one carrying signal: a ladder has them by construction, a standard curve, a control or
        a sample lane must carry its own (owner, 2026-10-05: every lane, never a lane-type
        exemption). Called on the integrated lanes, before any of them is normalised, so the
        refusal names every lane at once and nothing is computed or saved. Lane Total needs nothing.

        Raises:
            NormalizationRefused: naming each lane without the band.
        """
        if self.params.normalization_method != NormalizationMethod.LOADING_CONTROL:
            return

        from gel_analyzer.models import Lane

        type_labels = dict(Lane.LaneType.choices)
        lacking = [
            f"lane {lane.lane_number} ({type_labels.get(lane.lane_type, lane.lane_type)})"
            for lane in lane_results
            if lane.peaks and self._loading_control_area(lane) <= 0
        ]
        if lacking:
            raise NormalizationRefused(
                "Loading Control divides each band by the MW Reference bands of its lane, and these "
                f"lanes have none carrying signal: {', '.join(lacking)}. Add an MW Reference band to "
                "each, or choose Lane Total."
            )

    def normalize_gel(
        self,
        lane_results: list[LaneDensitometryResultData],
    ) -> list[LaneDensitometryResultData]:
        """
        Normalize bands across all lanes in a gel.

        Computes relative_percent_gel for each band based on gel total,
        after the per-lane normalization of the method asked for.

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

    @staticmethod
    def _loading_control_area(lane_result: LaneDensitometryResultData) -> float:
        """The lane's loading control: the summed area of its MW_REFERENCE bands (0 without one)."""
        return sum(p.corrected_area for p in lane_result.peaks if p.band_type == "MW_REFERENCE")

    def _normalize_by_loading_control(
        self,
        lane_result: LaneDensitometryResultData,
    ) -> None:
        """
        Normalize by the lane's loading control: its MW_REFERENCE bands' total area.

        Args:
            lane_result: Lane result to normalize in-place.

        Raises:
            NormalizationRefused: the lane has no MW_REFERENCE band carrying signal. A run is
                refused for the whole gel first (``refuse_unless_normalizable``); never a fallback.
        """
        reference_area = self._loading_control_area(lane_result)
        if reference_area <= 0:
            raise NormalizationRefused(
                f"Lane {lane_result.lane_number} has no MW Reference band carrying signal to normalise by."
            )

        # Normalize relative to loading control
        for peak in lane_result.peaks:
            if peak.corrected_area > 0:
                peak.relative_percent_lane = (peak.corrected_area / reference_area) * 100.0
            else:
                peak.relative_percent_lane = 0.0

        # Lane total is still computed normally
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

    The mean purity is not one of them: it needs the gel (``services/mean_purity.py``), and the
    service computes it.

    Args:
        lane_results: List of lane densitometry results.

    Returns:
        Dictionary with gel statistics.
    """
    successful_lanes = [r for r in lane_results if r.success]

    if not successful_lanes:
        return {
            "gel_total_area": 0.0,
            "total_bands": 0,
            "total_poi_bands": 0,
        }

    gel_total = sum(r.total_integrated_area for r in successful_lanes)
    total_bands = sum(len(r.peaks) for r in successful_lanes)

    # Count POI bands
    total_poi_bands = sum(sum(1 for p in r.peaks if p.band_type == "POI") for r in successful_lanes)

    return {
        "gel_total_area": gel_total,
        "total_bands": total_bands,
        "total_poi_bands": total_poi_bands,
    }
