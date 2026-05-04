"""
Intensity profile extraction from gel lane regions.

Extracts 1D intensity profiles from lanes by averaging pixel intensities
across a configurable portion of the lane width at each Y position.
Handles both rectangle and polygon lane shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import Lane

from .models import BandDetectionParams, IntensityProfile

logger = get_logger(__name__)


class IntensityProfileExtractor:
    """
    Extract 1D intensity profile from a gel lane region.

    The profile is computed by averaging pixel intensities across
    a configurable portion of the lane width at each Y position.
    This creates a 1D signal where peaks correspond to protein bands.

    Usage:
        extractor = IntensityProfileExtractor(params)
        profile = extractor.extract_profile(image, lane)
    """

    def __init__(self, params: BandDetectionParams):
        """
        Initialize extractor with detection parameters.

        Args:
            params: Detection parameters controlling profile extraction.
        """
        self.params = params

    def extract_profile(
        self,
        image: np.ndarray,
        lane: Lane,
    ) -> IntensityProfile:
        """
        Extract intensity profile from lane region.

        For each Y position within the lane, computes the average
        intensity across the center portion of the lane width
        (controlled by profile_width_percent parameter).

        Args:
            image: Grayscale image as numpy array (H, W) or (H, W, C).
                  If color image provided, it will be converted to grayscale.
            lane: Lane model instance with geometry (bbox or polygon).

        Returns:
            IntensityProfile with raw intensities ready for processing.
        """
        # Ensure grayscale
        if len(image.shape) == 3:
            # RGB to grayscale using luminance formula, or just take first channel
            image = np.dot(image[..., :3], [0.299, 0.587, 0.114]) if image.shape[2] == 3 else image[..., 0]

        # Get lane bounding box
        bbox = lane.bbox
        lane_x = int(bbox["x"])
        lane_y = int(bbox["y"])
        lane_width = int(bbox["width"])
        lane_height = int(bbox["height"])

        # Calculate profile extraction window (center portion of lane)
        margin_px = int(lane_width * (100 - self.params.profile_width_percent) / 200)
        profile_x_start = lane_x + margin_px
        profile_x_end = lane_x + lane_width - margin_px

        # Apply edge margin (exclude top/bottom percentage of lane)
        edge_margin_px = int(lane_height * self.params.lane_edge_margin_percent / 100)
        y_start = lane_y + edge_margin_px
        y_end = lane_y + lane_height - edge_margin_px

        # Validate bounds against image dimensions
        h, w = image.shape[:2]
        profile_x_start = max(0, min(profile_x_start, w - 1))
        profile_x_end = max(profile_x_start + 1, min(profile_x_end, w))
        y_start = max(0, min(y_start, h - 1))
        y_end = max(y_start + 1, min(y_end, h))

        logger.debug(
            f"Extracting profile from lane {lane.lane_number}: "
            f"x=[{profile_x_start}:{profile_x_end}], y=[{y_start}:{y_end}]"
        )

        # Handle polygon lanes with per-row width adjustment
        if lane.has_polygon and lane.polygon:
            return self._extract_from_polygon(image, lane, y_start, y_end, profile_x_start, profile_x_end)

        # Extract profile for rectangle lanes
        y_positions = []
        raw_intensities = []

        for y in range(y_start, y_end):
            # Extract row slice and compute average
            row_slice = image[y, profile_x_start:profile_x_end]
            avg_intensity = float(np.mean(row_slice))

            y_positions.append(y)
            raw_intensities.append(avg_intensity)

        logger.debug(f"Extracted {len(y_positions)} profile points")

        return IntensityProfile(
            y_positions=y_positions,
            raw_intensities=raw_intensities,
            processed_intensities=[],  # Filled by ProfileProcessor
            background=[],
            lane_x=lane_x,
            lane_y=lane_y,
            lane_width=lane_width,
            lane_height=lane_height,
            profile_x_start=profile_x_start,
            profile_x_end=profile_x_end,
        )

    def _extract_from_polygon(
        self,
        image: np.ndarray,
        lane: Lane,
        y_start: int,
        y_end: int,
        default_x_start: int,
        default_x_end: int,
    ) -> IntensityProfile:
        """
        Extract profile from polygon-shaped lane.

        For each Y position, finds the intersection with the polygon
        edges and averages intensities within that horizontal slice.
        This handles non-rectangular lane shapes (common with YOLO detection).

        Args:
            image: Grayscale image array.
            lane: Lane with polygon geometry.
            y_start: Starting Y position.
            y_end: Ending Y position.
            default_x_start: Default X start (used for metadata).
            default_x_end: Default X end (used for metadata).

        Returns:
            IntensityProfile extracted from polygon region.
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available, falling back to bbox extraction")
            # Fall back to simple rectangle extraction
            return self._extract_from_bbox_fallback(image, lane, y_start, y_end, default_x_start, default_x_end)

        polygon = np.array(lane.polygon, dtype=np.int32)
        bbox = lane.bbox

        # Create mask for the polygon
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 255)

        y_positions = []
        raw_intensities = []

        for y in range(y_start, y_end):
            # Find X range within polygon at this Y
            row_mask = mask[y, :]
            valid_x = np.where(row_mask > 0)[0]

            if len(valid_x) == 0:
                # No valid pixels at this Y, skip
                continue

            # Apply profile width constraint to polygon width at this row
            x_min, x_max = valid_x[0], valid_x[-1]
            width_at_y = x_max - x_min
            margin = int(width_at_y * (100 - self.params.profile_width_percent) / 200)

            x_start = x_min + margin
            x_end = x_max - margin

            if x_end <= x_start:
                # Margin too large for this row, use full width
                x_start = x_min
                x_end = x_max

            # Extract row slice and compute average
            row_slice = image[y, x_start:x_end]
            if len(row_slice) > 0:
                avg_intensity = float(np.mean(row_slice))
                y_positions.append(y)
                raw_intensities.append(avg_intensity)

        logger.debug(f"Extracted {len(y_positions)} profile points from polygon lane")

        return IntensityProfile(
            y_positions=y_positions,
            raw_intensities=raw_intensities,
            processed_intensities=[],
            background=[],
            lane_x=int(bbox["x"]),
            lane_y=int(bbox["y"]),
            lane_width=int(bbox["width"]),
            lane_height=int(bbox["height"]),
            profile_x_start=default_x_start,
            profile_x_end=default_x_end,
        )

    def _extract_from_bbox_fallback(
        self,
        image: np.ndarray,
        lane: Lane,
        y_start: int,
        y_end: int,
        profile_x_start: int,
        profile_x_end: int,
    ) -> IntensityProfile:
        """
        Fallback extraction using bounding box when OpenCV unavailable.

        Args:
            image: Grayscale image array.
            lane: Lane model.
            y_start: Starting Y position.
            y_end: Ending Y position.
            profile_x_start: X start of profile window.
            profile_x_end: X end of profile window.

        Returns:
            IntensityProfile from bounding box region.
        """
        bbox = lane.bbox

        y_positions = []
        raw_intensities = []

        for y in range(y_start, y_end):
            row_slice = image[y, profile_x_start:profile_x_end]
            avg_intensity = float(np.mean(row_slice))
            y_positions.append(y)
            raw_intensities.append(avg_intensity)

        return IntensityProfile(
            y_positions=y_positions,
            raw_intensities=raw_intensities,
            processed_intensities=[],
            background=[],
            lane_x=int(bbox["x"]),
            lane_y=int(bbox["y"]),
            lane_width=int(bbox["width"]),
            lane_height=int(bbox["height"]),
            profile_x_start=profile_x_start,
            profile_x_end=profile_x_end,
        )
