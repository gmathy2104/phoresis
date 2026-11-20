# UNPLUGGED: legacy mode deprecated — derivative detection is the sole automatic method
"""
Peak detection in processed intensity profiles.

Uses scipy.signal.find_peaks with configurable parameters to identify
peaks that correspond to protein bands in gel electrophoresis images.

Key scipy.signal functions used:
- find_peaks: Identify peak positions
- peak_prominences: Measure peak prominence (height above baseline)
- peak_widths: Measure peak width at half-prominence
"""

from __future__ import annotations

import numpy as np
from scipy.signal import argrelmin, find_peaks, peak_prominences, peak_widths

from phoresis_core.logging_config import get_logger

from .models import BandDetectionParams, DetectedPeak, IntensityProfile
from .profile_processor import estimate_noise

logger = get_logger(__name__)


def find_valleys(data: np.ndarray, min_distance: int = 5) -> np.ndarray:
    """Find local minima in a 1D signal, including boundaries.

    Args:
        data: 1D intensity array.
        min_distance: Minimum distance between valleys (controls `order` param).

    Returns:
        Sorted array of valley indices, always including 0 and len(data)-1.
    """
    order = max(2, min_distance // 2)
    valley_indices = argrelmin(data, order=order)[0]
    # Always include profile boundaries as implicit valleys
    all_valleys = np.concatenate([[0], valley_indices, [len(data) - 1]])
    return np.sort(np.unique(all_valleys))


class PeakDetector:
    """
    Detect peaks (bands) in intensity profiles using scipy.signal.find_peaks.

    Converts user-friendly sensitivity parameter to scipy peak detection
    thresholds, then filters results based on width constraints.

    Usage:
        detector = PeakDetector(params)
        peaks = detector.find_peaks(processed_profile)
    """

    def __init__(self, params: BandDetectionParams):
        """
        Initialize detector with detection parameters.

        Args:
            params: Detection parameters including sensitivity, width bounds.
        """
        self.params = params

    def find_peaks(self, profile: IntensityProfile) -> list[DetectedPeak]:
        """
        Find peaks in the processed intensity profile.

        The sensitivity parameter (0-1) is mapped to a prominence threshold:
        - sensitivity=0: Only very prominent peaks (strict)
        - sensitivity=1: Even faint peaks detected (permissive)

        Args:
            profile: IntensityProfile with processed_intensities filled.

        Returns:
            List of DetectedPeak objects, sorted by Y position.
        """
        if not profile.processed_intensities:
            logger.warning("No processed intensities, cannot detect peaks")
            return []

        data = np.array(profile.processed_intensities, dtype=np.float64)
        y_positions = np.array(profile.y_positions)

        if len(data) < 5:
            logger.warning("Profile too short for peak detection")
            return []

        # Calculate dynamic thresholds
        signal_range = np.ptp(data)  # Peak-to-peak range
        noise = estimate_noise(data)

        if signal_range == 0:
            logger.warning("No signal variation, no peaks to detect")
            return []

        # Map sensitivity (0-1) to prominence threshold
        # Higher sensitivity = lower threshold = more peaks detected
        # At sensitivity=0: threshold = 30% of signal range (strict)
        # At sensitivity=1: threshold = 2x noise level (permissive)
        min_prominence = max(noise * 2, signal_range * 0.02)  # Minimum viable
        max_prominence = signal_range * 0.3  # Strict threshold

        prominence_threshold = max_prominence - ((max_prominence - min_prominence) * self.params.sensitivity)

        # Also apply user's peak_prominence as relative constraint
        rel_prominence = signal_range * self.params.peak_prominence
        prominence_threshold = max(prominence_threshold, rel_prominence)

        # Height threshold: peak must be above some fraction of signal
        background_level = np.percentile(data, 10)  # Lower 10% as baseline
        height_threshold = max(background_level * self.params.min_intensity_ratio, noise * 3)  # At least 3x noise

        logger.info(
            f"Peak detection: sensitivity={self.params.sensitivity:.2f}, "
            f"signal_range={signal_range:.2f}, noise={noise:.2f}, "
            f"prominence_threshold={prominence_threshold:.2f}, "
            f"height_threshold={height_threshold:.2f}, "
            f"distance={self.params.peak_distance}, "
            f"width_range=[{max(1, self.params.min_band_width_px // 2)}, {self.params.max_band_width_px}]"
        )

        # Find peaks using scipy
        try:
            peak_indices, properties = find_peaks(
                data,
                height=height_threshold,
                prominence=prominence_threshold,
                distance=self.params.peak_distance,
                width=(max(1, self.params.min_band_width_px // 2), self.params.max_band_width_px),
            )
        except ValueError as e:
            logger.warning(f"find_peaks with width constraint failed: {e}")
            # Fallback with fewer constraints
            try:
                peak_indices, properties = find_peaks(
                    data,
                    height=height_threshold,
                    prominence=prominence_threshold,
                    distance=self.params.peak_distance,
                )
            except ValueError as e2:
                logger.warning(f"find_peaks fallback also failed: {e2}")
                return []

        logger.info(f"scipy.find_peaks found {len(peak_indices)} candidates")

        if len(peak_indices) == 0:
            return []

        # Calculate additional properties
        try:
            prominences, left_bases, right_bases = peak_prominences(data, peak_indices)
        except ValueError:
            prominences = np.zeros(len(peak_indices))
            left_bases = np.zeros(len(peak_indices), dtype=int)
            right_bases = np.full(len(peak_indices), len(data) - 1, dtype=int)

        # Find valleys (local minima) for tighter band boundaries
        all_valleys = find_valleys(data, self.params.peak_distance)
        profile.valley_indices = all_valleys.tolist()

        try:
            widths, width_heights, left_ips, right_ips = peak_widths(data, peak_indices, rel_height=0.5)
        except ValueError:
            widths = np.full(len(peak_indices), self.params.min_band_width_px)
            left_ips = peak_indices - self.params.min_band_width_px // 2
            right_ips = peak_indices + self.params.min_band_width_px // 2

        # Build DetectedPeak objects with filtering
        detected_peaks = []

        for i, idx in enumerate(peak_indices):
            width_px = int(widths[i])

            # Filter by width constraints
            if width_px > self.params.max_band_width_px:
                logger.debug(f"Peak at {idx} rejected: width {width_px} > max")
                continue
            if width_px < self.params.min_band_width_px:
                logger.debug(f"Peak at {idx} rejected: width {width_px} < min")
                continue

            # Calculate SNR
            peak_height = data[idx] - background_level
            snr = peak_height / noise if noise > 0 else 10.0

            # Require minimum SNR
            if snr < 2.0:
                logger.debug(f"Peak at {idx} rejected: SNR {snr:.1f} < 2.0")
                continue

            # Calculate integrated area under peak
            left_idx = max(0, int(left_ips[i]))
            right_idx = min(len(data) - 1, int(right_ips[i]))
            area = float(np.trapezoid(data[left_idx : right_idx + 1]))

            # Assign nearest valleys as band boundaries
            left_v = all_valleys[all_valleys < idx]
            right_v = all_valleys[all_valleys > idx]
            left_valley = int(left_v[-1]) if len(left_v) > 0 else 0
            right_valley = int(right_v[0]) if len(right_v) > 0 else len(data) - 1

            peak = DetectedPeak(
                profile_index=int(idx),
                y_position=int(y_positions[idx]),
                height=float(data[idx]),
                prominence=float(prominences[i]),
                width_px=width_px,
                left_base=int(left_bases[i]),
                right_base=int(right_bases[i]),
                left_valley=left_valley,
                right_valley=right_valley,
                snr=float(snr),
                area=area,
            )
            detected_peaks.append(peak)

        logger.info(
            f"After filtering: {len(detected_peaks)} peaks accepted, {len(peak_indices) - len(detected_peaks)} rejected"
        )

        return detected_peaks
