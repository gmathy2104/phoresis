"""
Build band geometry (bounding boxes) from detected peaks.

Converts peak positions and widths into band bounding boxes,
ensuring all bands are within lane boundaries.

NOTE: Polygon refinement is handled by MobileSAM on the frontend.
The backend returns bands with bbox only (polygon=[]), and the
frontend automatically refines them using SAM for precise segmentation.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import Lane

from .models import BandDetectionParams, BandDetectionSource, DetectedBand, DetectedPeak, IntensityProfile

logger = get_logger(__name__)


class BandGeometryBuilder:
    """
    Build band geometry from detected peaks.

    Creates bounding boxes spanning the lane width at each peak's
    Y position, with height based on peak width. Optionally refines
    boundaries using edge detection.

    Usage:
        builder = BandGeometryBuilder(params)
        bands = builder.build_bands(peaks, profile, lane, image)
    """

    def __init__(self, params: BandDetectionParams):
        """
        Initialize builder with detection parameters.

        Args:
            params: Detection parameters for geometry constraints.
        """
        self.params = params

    def build_bands(
        self,
        peaks: list[DetectedPeak],
        profile: IntensityProfile,
        lane: Lane,
        image: np.ndarray | None = None,
    ) -> list[DetectedBand]:
        """
        Convert detected peaks to DetectedBand objects with geometry.

        Args:
            peaks: List of DetectedPeak from PeakDetector.
            profile: IntensityProfile for coordinate reference.
            lane: Lane model for boundary constraints.
            image: Optional image for intensity calculation and polygon refinement.

        Returns:
            List of DetectedBand objects sorted by Y position (top to bottom).
        """
        if not peaks:
            return []

        bands = []
        bbox = lane.bbox

        lane_x = int(bbox["x"])
        lane_y = int(bbox["y"])
        lane_width = int(bbox["width"])
        lane_height = int(bbox["height"])

        for peak in peaks:
            band_center_y = peak.y_position

            # Band boundary strategy:
            # For closely-spaced peaks, valleys (local minima) are tighter than
            # prominence bases. For isolated/edge peaks, prominence bases are
            # tighter (valleys extend to profile boundaries). We compute both
            # and pick the TIGHTER pair, giving optimal boundaries in all cases.
            n_positions = len(profile.y_positions)

            has_valleys = (
                peak.left_valley >= 0
                and peak.right_valley >= 0
                and peak.left_valley < n_positions
                and peak.right_valley < n_positions
            )
            has_bases = peak.left_base < n_positions and peak.right_base < n_positions

            if has_valleys and has_bases:
                # Both available — pick the tighter (closer to peak) boundary
                # on each side independently
                valley_top = profile.y_positions[peak.left_valley]
                valley_bot = profile.y_positions[peak.right_valley]
                base_top = profile.y_positions[peak.left_base]
                base_bot = profile.y_positions[min(peak.right_base, n_positions - 1)]
                # For top: pick the one CLOSER to the peak (larger Y value)
                bbox_y = max(valley_top, base_top)
                # For bottom: pick the one CLOSER to the peak (smaller Y value)
                bbox_bottom = min(valley_bot, base_bot)
                bbox_height = max(
                    bbox_bottom - bbox_y,
                    self.params.min_band_width_px,
                )
            elif has_valleys:
                bbox_y = profile.y_positions[peak.left_valley]
                bbox_bottom = profile.y_positions[peak.right_valley]
                bbox_height = max(
                    bbox_bottom - bbox_y,
                    self.params.min_band_width_px,
                )
            elif has_bases:
                base_top_y = profile.y_positions[peak.left_base]
                base_bot_y = profile.y_positions[min(peak.right_base, n_positions - 1)]
                bbox_y = base_top_y
                bbox_height = max(
                    base_bot_y - base_top_y,
                    self.params.min_band_width_px,
                )
            else:
                # FWHM-based boundaries (last resort)
                band_half_height = max(
                    peak.width_px // 2,
                    self.params.min_band_width_px // 2,
                )
                bbox_y = band_center_y - band_half_height
                bbox_height = 2 * band_half_height

            # Cap at max_band_width_px to avoid absurd boxes on unresolved peaks
            if bbox_height > self.params.max_band_width_px:
                overshoot = bbox_height - self.params.max_band_width_px
                bbox_y += overshoot // 2
                bbox_height = self.params.max_band_width_px

            # Constrain to lane boundaries
            if bbox_y < lane_y:
                bbox_y = lane_y
            if bbox_y + bbox_height > lane_y + lane_height:
                bbox_height = lane_y + lane_height - bbox_y

            # Band spans full lane width (horizontal extent) -- for a polygon lane, its span at the band's centre row
            # (spec 2026-10-10 §5.1: a tilted lane's box is wider than the lane); a rectangle keeps its box.
            bbox_x, bbox_width = self._lane_span(lane, band_center_y, lane_x, lane_width)

            # Calculate confidence from SNR and prominence
            confidence = self._calculate_confidence(peak, profile)

            # Calculate raw intensity if image provided
            intensity_raw = 0.0
            area_pixels = 0
            if image is not None:
                intensity_raw, area_pixels = self._calculate_intensity(image, bbox_x, bbox_y, bbox_width, bbox_height)

            band = DetectedBand(
                position_y=band_center_y,
                bbox_x=bbox_x,
                bbox_y=bbox_y,
                bbox_width=bbox_width,
                bbox_height=bbox_height,
                polygon=[],  # Empty - will be refined by SAM on frontend
                confidence=confidence,
                detection_source=BandDetectionSource.AUTO,
                intensity_raw=intensity_raw,
                intensity_peak=peak.height,
                area_pixels=area_pixels,
                peak_prominence=peak.prominence,
                peak_width_px=peak.width_px,
                snr=peak.snr,
            )

            bands.append(band)

        # Sort by Y position (top to bottom = migration order)
        bands.sort(key=lambda b: b.position_y)

        logger.debug(f"Built geometry for {len(bands)} bands")
        return bands

    @staticmethod
    def _lane_span(lane, row: float, lane_x: int, lane_width: int) -> tuple[int, int]:
        """(x, width) of the lane on ``row``: a polygon lane's own span (rounded outward), else its box."""
        polygon = getattr(lane, "polygon", None)
        is_polygon_lane = getattr(lane, "lane_shape", None) in ("QUADRILATERAL", "POLYGON")
        if not (is_polygon_lane and isinstance(polygon, list) and len(polygon) >= 3):
            return lane_x, lane_width
        # Imported here: this package is also loaded standalone, without its parent (tools/proofs).
        from gel_analyzer.services.lane_geometry.shape import lane_outline, span_at  # noqa: PLC0415

        outline = lane_outline(lane.lane_shape, lane.polygon, lane.x, lane.y, lane.width, lane.height)
        span = span_at(outline, row)
        if span is None:
            return lane_x, lane_width
        left, right = int(math.floor(span[0])), int(math.ceil(span[1]))
        return left, right - left

    def _calculate_confidence(
        self,
        peak: DetectedPeak,
        profile: IntensityProfile,
    ) -> float:
        """
        Calculate confidence score (0-1) for a detected band.

        Based on:
        - SNR (signal-to-noise ratio)
        - Peak prominence relative to signal range
        - Peak width relative to expected range

        Args:
            peak: DetectedPeak with metrics.
            profile: IntensityProfile for context.

        Returns:
            Confidence score between 0 and 1.
        """
        # SNR contribution (saturates at SNR=10)
        snr_score = min(peak.snr / 10, 1.0)

        # Prominence contribution (relative to signal range)
        if profile.processed_intensities:
            signal_range = profile.signal_range
            prom_score = min(peak.prominence / signal_range, 1.0) if signal_range > 0 else 0.5
        else:
            prom_score = 0.5

        # Width contribution (penalize extremes)
        optimal_width = (self.params.min_band_width_px + self.params.max_band_width_px) / 2
        if optimal_width > 0:
            width_ratio = peak.width_px / optimal_width
            # Score is 1 at optimal, decreases towards 0 at extremes
            width_score = 1.0 - min(abs(1.0 - width_ratio) / 2, 1.0)
        else:
            width_score = 0.5

        # Weighted combination
        confidence = 0.5 * snr_score + 0.3 * prom_score + 0.2 * width_score

        return round(max(0.0, min(1.0, confidence)), 3)

    def _calculate_intensity(
        self,
        image: np.ndarray,
        bbox_x: int,
        bbox_y: int,
        bbox_width: int,
        bbox_height: int,
    ) -> tuple[float, int]:
        """
        Calculate integrated intensity within band region.

        Args:
            image: Grayscale image array.
            bbox_x, bbox_y, bbox_width, bbox_height: Band bounding box.

        Returns:
            Tuple of (intensity_raw, area_pixels).
        """
        h, w = image.shape[:2]

        # Ensure bounds are within image
        y_start = max(0, bbox_y)
        y_end = min(h, bbox_y + bbox_height)
        x_start = max(0, bbox_x)
        x_end = min(w, bbox_x + bbox_width)

        if y_end <= y_start or x_end <= x_start:
            return 0.0, 0

        band_region = image[y_start:y_end, x_start:x_end]
        intensity_raw = float(np.sum(band_region))
        area_pixels = band_region.size

        return intensity_raw, area_pixels

    # NOTE: Polygon refinement removed - now handled by MobileSAM on frontend
    # See: gel_analyzer/static/gel_analyzer/js/gel-viewer/inference/sam-decoder-engine.js
    # The backend returns bands with empty polygons (bbox only), and the frontend
    # automatically refines them using SAM for precise segmentation.
