# UNPLUGGED: boundary mode deprecated — derivative detection is the sole automatic method
"""
Boundary-centric peak integration for band detection.

Inspired by HPLC chromatography integration software. Instead of
finding peaks first and then determining boundaries (peak-centric),
this module finds boundaries first and then checks for peaks between
them (boundary-centric).

Algorithm:
1. Find above-threshold segments (contiguous regions where intensity > T)
2. For each segment, find internal valleys and filter by depth
3. Split segments at valleys into sub-segments (= band candidates)
4. For each sub-segment: find peak, classify boundaries, compute area

Boundary types:
- BASELINE: The boundary occurs where the profile crosses the threshold
- VALLEY: The boundary occurs at a local minimum between overlapping peaks
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from phoresis_core.logging_config import get_logger

from .models import (
    BandDetectionParams,
    DetectedPeak,
    IntensityProfile,
)
from .profile_processor import estimate_noise

logger = get_logger(__name__)


class BoundaryType(StrEnum):
    """Type of integration boundary."""

    BASELINE = "baseline"
    VALLEY = "valley"


@dataclass
class IntegrationBoundary:
    """A boundary point of an integrated band."""

    index: int  # Profile array index
    boundary_type: BoundaryType
    value: float  # Intensity at boundary


@dataclass
class IntegratedBand:
    """A band detected by the boundary-centric integration algorithm."""

    peak_index: int
    peak_height: float
    left_boundary: IntegrationBoundary
    right_boundary: IntegrationBoundary
    area: float  # np.trapezoid between boundaries
    width_px: int  # Width in profile indices
    snr: float


class PeakIntegrator:
    """
    Boundary-centric peak integration for gel electrophoresis profiles.

    Finds contiguous above-threshold segments, splits them at significant
    valleys, and integrates each sub-segment as a band candidate.
    """

    def __init__(self, params: BandDetectionParams):
        self.params = params

    def integrate(self, profile: IntensityProfile) -> tuple[list[IntegratedBand], float]:
        """
        Run boundary-centric integration on a processed intensity profile.

        Args:
            profile: IntensityProfile with processed_intensities filled.

        Returns:
            Tuple of (list of IntegratedBand, threshold value used).
        """
        if not profile.processed_intensities:
            logger.warning("No processed intensities for integration")
            return [], 0.0

        data = np.array(profile.processed_intensities, dtype=np.float64)

        if len(data) < 5:
            logger.warning("Profile too short for integration")
            return [], 0.0

        # Compute threshold
        if self.params.min_peak_height > 0:
            threshold = self.params.min_peak_height
        else:
            threshold = self._compute_auto_threshold(data)

        if threshold <= 0:
            logger.warning("Threshold is zero or negative, no bands detectable")
            return [], 0.0

        noise = estimate_noise(data)
        min_valley_depth = noise * self.params.min_valley_depth_factor

        logger.info(
            f"Peak integration: threshold={threshold:.2f}, "
            f"noise={noise:.2f}, min_valley_depth={min_valley_depth:.2f}, "
            f"method=boundary"
        )

        # Step 1: Find above-threshold segments
        segments = self._find_segments(data, threshold)

        if not segments:
            logger.info("No above-threshold segments found")
            return [], threshold

        logger.info(f"Found {len(segments)} above-threshold segments")

        # Step 2-3: For each segment, find valleys, split, and integrate
        bands = []
        for seg_start, seg_end in segments:
            valleys = self._find_valleys_in_segment(data, seg_start, seg_end, min_valley_depth)
            seg_bands = self._split_and_integrate(data, seg_start, seg_end, valleys, threshold, noise)
            bands.extend(seg_bands)

        # Filter by width constraints
        filtered = []
        for band in bands:
            if band.width_px < self.params.min_band_width_px:
                logger.debug(
                    f"Band at {band.peak_index} rejected: width {band.width_px} < min {self.params.min_band_width_px}"
                )
                continue
            if band.width_px > self.params.max_band_width_px:
                logger.debug(
                    f"Band at {band.peak_index} rejected: width {band.width_px} > max {self.params.max_band_width_px}"
                )
                continue
            if band.snr < 2.0:
                logger.debug(f"Band at {band.peak_index} rejected: SNR {band.snr:.1f} < 2.0")
                continue
            filtered.append(band)

        # Enforce minimum peak distance
        if self.params.peak_distance > 1 and len(filtered) > 1:
            filtered = self._enforce_min_distance(filtered)

        logger.info(f"Integration complete: {len(filtered)} bands accepted from {len(bands)} candidates")

        return filtered, threshold

    def _find_segments(self, data: np.ndarray, threshold: float) -> list[tuple[int, int]]:
        """
        Find contiguous above-threshold regions.

        Args:
            data: Processed intensity array.
            threshold: Minimum intensity threshold.

        Returns:
            List of (start_idx, end_idx) tuples for each segment.
        """
        above = data > threshold
        segments = []
        in_segment = False
        start = 0

        for i in range(len(above)):
            if above[i] and not in_segment:
                start = i
                in_segment = True
            elif not above[i] and in_segment:
                segments.append((start, i - 1))
                in_segment = False

        # Close trailing segment
        if in_segment:
            segments.append((start, len(data) - 1))

        return segments

    def _find_valleys_in_segment(
        self,
        data: np.ndarray,
        seg_start: int,
        seg_end: int,
        min_valley_depth: float,
    ) -> list[int]:
        """
        Find significant local minima within a segment.

        A valley is kept only if it is deep enough relative to its
        flanking peaks, preventing splitting on minor noise dips.

        Args:
            data: Full profile intensity array.
            seg_start: Start index of segment.
            seg_end: End index of segment.
            min_valley_depth: Minimum depth to qualify as a split point.

        Returns:
            List of valley indices (in full-profile coordinates).
        """
        if seg_end - seg_start < 4:
            return []

        segment = data[seg_start : seg_end + 1]

        # Find all local minima in the segment
        valley_indices = []
        for i in range(1, len(segment) - 1):
            if (
                segment[i] <= segment[i - 1]
                and segment[i] <= segment[i + 1]
                # Check it's actually lower than at least one neighbor (not plateau)
                and (segment[i] < segment[i - 1] or segment[i] < segment[i + 1])
            ):
                valley_indices.append(i)

        if not valley_indices:
            return []

        # Filter by depth: valley must be significantly lower than flanking peaks
        significant_valleys = []
        for vi in valley_indices:
            abs_vi = seg_start + vi

            # Find max to the left (between segment start and valley)
            left_peak = float(np.max(data[seg_start : abs_vi + 1]))
            # Find max to the right (between valley and segment end)
            right_peak = float(np.max(data[abs_vi : seg_end + 1]))

            # Depth = min of flanking peaks minus valley value
            depth = min(left_peak, right_peak) - data[abs_vi]

            if depth >= min_valley_depth:
                significant_valleys.append(abs_vi)

        return significant_valleys

    def _split_and_integrate(
        self,
        data: np.ndarray,
        seg_start: int,
        seg_end: int,
        valleys: list[int],
        threshold: float,
        noise: float,
    ) -> list[IntegratedBand]:
        """
        Split a segment at valley points and integrate each sub-segment.

        Args:
            data: Full profile intensity array.
            seg_start: Start index of segment.
            seg_end: End index of segment.
            valleys: Valley indices for splitting.
            threshold: Detection threshold.
            noise: Estimated noise level.

        Returns:
            List of IntegratedBand objects.
        """
        # Build sub-segment boundaries
        boundaries = [seg_start] + sorted(valleys) + [seg_end]

        bands = []
        for i in range(len(boundaries) - 1):
            left_idx = boundaries[i]
            right_idx = boundaries[i + 1]

            sub_data = data[left_idx : right_idx + 1]
            if len(sub_data) < 2:
                continue

            # Find peak within sub-segment
            peak_offset = int(np.argmax(sub_data))
            peak_idx = left_idx + peak_offset
            peak_height = float(data[peak_idx])

            # Peak must exceed threshold
            if peak_height <= threshold:
                continue

            # Classify boundaries
            left_type = BoundaryType.BASELINE if left_idx == seg_start else BoundaryType.VALLEY
            right_type = BoundaryType.BASELINE if right_idx == seg_end else BoundaryType.VALLEY

            # Compute area (trapezoidal integration)
            area = float(np.trapezoid(sub_data))

            # Width
            width_px = right_idx - left_idx

            # SNR
            snr = peak_height / noise if noise > 0 else 10.0

            band = IntegratedBand(
                peak_index=peak_idx,
                peak_height=peak_height,
                left_boundary=IntegrationBoundary(
                    index=left_idx,
                    boundary_type=left_type,
                    value=float(data[left_idx]),
                ),
                right_boundary=IntegrationBoundary(
                    index=right_idx,
                    boundary_type=right_type,
                    value=float(data[right_idx]),
                ),
                area=area,
                width_px=width_px,
                snr=snr,
            )
            bands.append(band)

        return bands

    def _compute_auto_threshold(self, data: np.ndarray) -> float:
        """
        Auto-calculate threshold from noise level.

        Uses MAD-based noise estimation multiplied by the user's
        threshold_factor.

        Args:
            data: Processed intensity array.

        Returns:
            Threshold value.
        """
        noise = estimate_noise(data)
        threshold = noise * self.params.threshold_factor

        # Ensure threshold is not above the signal range
        signal_max = float(np.max(data))
        if threshold > signal_max * 0.9:
            threshold = signal_max * 0.1

        logger.debug(
            f"Auto-threshold: noise={noise:.2f}, factor={self.params.threshold_factor}, threshold={threshold:.2f}"
        )

        return threshold

    def _enforce_min_distance(self, bands: list[IntegratedBand]) -> list[IntegratedBand]:
        """
        Remove bands that are closer than min peak distance, keeping
        the taller peak.

        Args:
            bands: List of IntegratedBand sorted by peak_index.

        Returns:
            Filtered list with minimum distance enforced.
        """
        if not bands:
            return bands

        # Sort by peak_index
        sorted_bands = sorted(bands, key=lambda b: b.peak_index)
        result = [sorted_bands[0]]

        for band in sorted_bands[1:]:
            prev = result[-1]
            distance = band.peak_index - prev.peak_index

            if distance < self.params.peak_distance:
                # Keep the taller peak
                if band.peak_height > prev.peak_height:
                    result[-1] = band
            else:
                result.append(band)

        return result


def integrated_bands_to_peaks(
    bands: list[IntegratedBand],
    profile: IntensityProfile,
) -> list[DetectedPeak]:
    """
    Convert IntegratedBand objects to DetectedPeak objects.

    This bridges the boundary-centric integrator into the existing
    geometry builder pipeline which expects DetectedPeak inputs.

    Args:
        bands: List of IntegratedBand from PeakIntegrator.
        profile: The IntensityProfile used for detection.

    Returns:
        List of DetectedPeak objects.
    """
    y_positions = profile.y_positions
    peaks = []

    for band in bands:
        idx = band.peak_index
        y_pos = y_positions[idx] if idx < len(y_positions) else 0

        peak = DetectedPeak(
            profile_index=idx,
            y_position=int(y_pos),
            height=band.peak_height,
            prominence=band.peak_height
            - max(
                band.left_boundary.value,
                band.right_boundary.value,
            ),
            width_px=band.width_px,
            left_base=band.left_boundary.index,
            right_base=band.right_boundary.index,
            left_valley=band.left_boundary.index,
            right_valley=band.right_boundary.index,
            snr=band.snr,
            area=band.area,
        )
        peaks.append(peak)

    return peaks
