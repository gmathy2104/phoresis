"""
Peak matching service for correlating detected peaks with existing bands.

Matches peaks detected from intensity profiles to Band model instances
based on Y position proximity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import Band

from .models import DetectedPeakWithMatch, PeakDetectionResult

logger = get_logger(__name__)


class PeakMatchingService:
    """
    Match detected peaks to existing Band annotations.

    Identifies orphan peaks (peaks without corresponding bands) and
    updates peak objects with matching information.

    Usage:
        service = PeakMatchingService(tolerance_px=15)
        result = service.match_peaks_to_bands(peaks, bands, lane_id)
    """

    def __init__(self, tolerance_px: int = 15):
        """
        Initialize matching service.

        Args:
            tolerance_px: Maximum distance in pixels for a valid match.
        """
        self.tolerance_px = tolerance_px

    def match_peaks_to_bands(
        self,
        peaks: list[DetectedPeakWithMatch],
        bands: list[Band],
        lane_id: int,
    ) -> PeakDetectionResult:
        """
        Match detected peaks to existing bands.

        Updates each peak's matching fields (is_orphan, matched_band_id, etc.)
        and returns a summary result.

        Args:
            peaks: List of detected peaks from AdvancedPeakDetector.
            bands: List of Band model instances for the lane.
            lane_id: ID of the lane being processed.

        Returns:
            PeakDetectionResult with matched peaks and statistics.
        """
        result = PeakDetectionResult(
            lane_id=lane_id,
            peaks=peaks,
            total_peaks=len(peaks),
        )

        if not peaks:
            result.success = True
            return result

        # Build band position lookup
        band_lookup = [(str(b.id), b.position_y) for b in bands]

        # Track which bands have been matched (to avoid double-matching)
        matched_band_ids = set()

        # Sort peaks by prominence (match strongest peaks first)
        sorted_peaks = sorted(peaks, key=lambda p: -p.prominence)

        for peak in sorted_peaks:
            best_match_id = None
            best_match_distance = None

            # Find closest unmatched band within tolerance
            for band_id, band_y in band_lookup:
                if band_id in matched_band_ids:
                    continue

                distance = abs(peak.y_position - band_y)

                if distance <= self.tolerance_px and (best_match_distance is None or distance < best_match_distance):
                    best_match_id = band_id
                    best_match_distance = distance

            # Update peak with match info
            if best_match_id is not None:
                peak.is_orphan = False
                peak.matched_band_id = best_match_id
                peak.match_distance_px = best_match_distance
                matched_band_ids.add(best_match_id)
            else:
                peak.is_orphan = True
                peak.matched_band_id = None
                peak.match_distance_px = None

        # Compute statistics
        result.orphan_count = sum(1 for p in peaks if p.is_orphan)
        result.matched_count = sum(1 for p in peaks if not p.is_orphan)
        result.shoulder_count = sum(1 for p in peaks if p.is_shoulder)
        result.success = True

        logger.debug(
            f"Lane {lane_id}: {result.total_peaks} peaks detected, "
            f"{result.matched_count} matched, {result.orphan_count} orphans"
        )

        return result

    def find_unmatched_bands(
        self,
        peaks: list[DetectedPeakWithMatch],
        bands: list[Band],
    ) -> list[Band]:
        """
        Find bands that have no matching peak.

        Useful for identifying bands that may be incorrectly positioned
        or have very low signal.

        Args:
            peaks: List of detected peaks with matching info.
            bands: List of Band model instances.

        Returns:
            List of bands without a matching peak.
        """
        matched_band_ids = {p.matched_band_id for p in peaks if p.matched_band_id is not None}

        unmatched = [band for band in bands if str(band.id) not in matched_band_ids]

        return unmatched


def match_peaks_and_bands(
    peaks: list[DetectedPeakWithMatch],
    bands: list[Band],
    lane_id: int,
    tolerance_px: int = 15,
) -> PeakDetectionResult:
    """
    Convenience function to match peaks to bands.

    Args:
        peaks: Detected peaks.
        bands: Existing bands.
        lane_id: Lane ID.
        tolerance_px: Match tolerance.

    Returns:
        PeakDetectionResult.
    """
    service = PeakMatchingService(tolerance_px=tolerance_px)
    return service.match_peaks_to_bands(peaks, bands, lane_id)
