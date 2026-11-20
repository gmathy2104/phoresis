"""
Advanced peak detection for electrophoresis profiles.

Provides robust peak detection including:
- Standard peak finding with scipy.signal.find_peaks
- Shoulder detection using second derivative analysis
- SNR-based filtering
- Peak property calculation (width, prominence, area)

Inspired by HPLC chromatography peak detection methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks, peak_prominences, peak_widths

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.services.band_detection.models import IntensityProfile

from .models import DetectedPeakWithMatch, PeakDetectionParams

logger = get_logger(__name__)


class AdvancedPeakDetector:
    """
    Advanced peak detection for SDS-PAGE electropherograms.

    Handles common challenges in gel densitometry:
    - Overlapping peaks
    - Shoulder peaks (partially resolved bands)
    - Noisy baselines
    - Asymmetric peaks

    Usage:
        detector = AdvancedPeakDetector(params)
        peaks = detector.detect_peaks(profile)
    """

    def __init__(self, params: PeakDetectionParams | None = None):
        """
        Initialize detector with parameters.

        Args:
            params: Detection parameters. Uses defaults if None.
        """
        self.params = params or PeakDetectionParams()

    def detect_peaks(
        self,
        profile: IntensityProfile,
    ) -> list[DetectedPeakWithMatch]:
        """
        Detect peaks in an intensity profile.

        Args:
            profile: IntensityProfile with y_positions and processed_intensities.

        Returns:
            List of DetectedPeakWithMatch objects.
        """
        y_positions = np.array(profile.y_positions)
        intensities = np.array(profile.processed_intensities)

        if len(intensities) < 5:
            logger.warning("Profile too short for peak detection")
            return []

        # Compute signal properties
        signal_range = float(np.max(intensities) - np.min(intensities))
        noise = self._estimate_noise(intensities)

        if signal_range <= 0:
            logger.warning("No signal range in profile")
            return []

        # Step 1: Standard peak detection with scipy
        main_peaks = self._find_main_peaks(intensities, y_positions, signal_range, noise)

        # Step 2: Shoulder detection (if enabled)
        if self.params.enable_shoulder_detection:
            shoulder_peaks = self._detect_shoulders(intensities, y_positions, main_peaks, signal_range, noise)
            # Merge peaks, avoiding duplicates
            all_peaks = self._merge_peaks(main_peaks, shoulder_peaks)
        else:
            all_peaks = main_peaks

        # Step 3: Calculate additional properties for each peak
        for peak in all_peaks:
            peak.snr = peak.height / noise if noise > 0 else 0.0

        # Sort by Y position (top to bottom)
        all_peaks.sort(key=lambda p: p.y_position)

        logger.debug(f"Detected {len(all_peaks)} peaks ({sum(1 for p in all_peaks if p.is_shoulder)} shoulders)")

        return all_peaks

    def _find_main_peaks(
        self,
        intensities: np.ndarray,
        y_positions: np.ndarray,
        signal_range: float,
        noise: float,
    ) -> list[DetectedPeakWithMatch]:
        """
        Find main peaks using scipy.signal.find_peaks.

        Args:
            intensities: Processed intensity values.
            y_positions: Y positions in image.
            signal_range: Max - min of signal.
            noise: Estimated noise level.

        Returns:
            List of detected peaks.
        """
        # Compute dynamic threshold based on sensitivity
        # Higher sensitivity = lower prominence threshold
        prominence_threshold = (1.0 - self.params.sensitivity) * 0.3 + 0.01
        min_prominence = prominence_threshold * signal_range

        # Height threshold: above noise floor
        min_height = 3 * noise + np.min(intensities)

        # Find peaks
        try:
            peak_indices, properties = find_peaks(
                intensities,
                height=min_height,
                prominence=min_prominence,
                distance=self.params.min_peak_distance,
                width=(self.params.min_width_px, self.params.max_width_px),
            )
        except Exception as e:
            logger.warning(f"find_peaks failed: {e}")
            return []

        if len(peak_indices) == 0:
            return []

        # Get peak properties
        prominences = peak_prominences(intensities, peak_indices)[0]
        widths, width_heights, left_ips, right_ips = peak_widths(intensities, peak_indices, rel_height=0.5)

        # Build DetectedPeakWithMatch objects
        peaks = []
        for i, idx in enumerate(peak_indices):
            # Calculate area using trapezoidal approximation
            left_idx = int(max(0, left_ips[i]))
            right_idx = int(min(len(intensities) - 1, right_ips[i]))
            area = (
                float(np.trapezoid(intensities[left_idx : right_idx + 1], y_positions[left_idx : right_idx + 1]))
                if right_idx > left_idx
                else 0.0
            )

            # Estimate sigma from width (FWHM = 2.355 * sigma)
            sigma = widths[i] / 2.355 if widths[i] > 0 else 5.0

            peak = DetectedPeakWithMatch(
                y_position=int(y_positions[idx]),
                height=float(intensities[idx]),
                prominence=float(prominences[i]),
                width_px=int(round(widths[i])),
                left_base=int(y_positions[left_idx]),
                right_base=int(y_positions[right_idx]),
                area=area,
                sigma=sigma,
                is_shoulder=False,
                is_orphan=True,  # Will be updated by matching service
            )
            peaks.append(peak)

        return peaks

    def _detect_shoulders(
        self,
        intensities: np.ndarray,
        y_positions: np.ndarray,
        main_peaks: list[DetectedPeakWithMatch],
        signal_range: float,
        noise: float,
    ) -> list[DetectedPeakWithMatch]:
        """
        Detect shoulder peaks using second derivative analysis.

        Shoulders appear as inflection points on the slopes of main peaks.
        We look for sign changes in the second derivative.

        Args:
            intensities: Processed intensity values.
            y_positions: Y positions in image.
            main_peaks: Already detected main peaks.
            signal_range: Signal range.
            noise: Noise level.

        Returns:
            List of shoulder peaks.
        """
        shoulders = []

        # Smooth slightly before derivative to reduce noise
        smoothed = uniform_filter1d(intensities, size=3)

        # First derivative
        first_deriv = np.gradient(smoothed)

        # Second derivative
        second_deriv = np.gradient(first_deriv)

        # Find zero-crossings (inflection points)
        zero_crossings = np.where(np.diff(np.sign(second_deriv)))[0]

        # Get main peak positions for exclusion
        main_peak_positions = {p.y_position for p in main_peaks}

        # Minimum shoulder prominence (lower than main peaks)
        min_shoulder_prominence = 0.02 * signal_range

        for zc_idx in zero_crossings:
            if zc_idx < 3 or zc_idx >= len(intensities) - 3:
                continue

            y_pos = int(y_positions[zc_idx])

            # Skip if too close to a main peak
            if any(abs(y_pos - mp) < 5 for mp in main_peak_positions):
                continue

            # Check if this is on a significant slope (first derivative is non-zero)
            slope_magnitude = abs(first_deriv[zc_idx])
            if slope_magnitude < 0.1 * np.std(first_deriv):
                continue

            # Check if there's actual intensity at this point
            intensity_at_point = intensities[zc_idx]
            local_min = np.min(intensities[max(0, zc_idx - 5) : zc_idx + 6])
            local_prominence = intensity_at_point - local_min

            if local_prominence < min_shoulder_prominence:
                continue

            # Check SNR
            if local_prominence < 2 * noise:
                continue

            # Estimate width (narrow for shoulders)
            width_estimate = 10  # Default narrow width

            # Create shoulder peak
            shoulder = DetectedPeakWithMatch(
                y_position=y_pos,
                height=float(intensity_at_point),
                prominence=float(local_prominence),
                width_px=width_estimate,
                left_base=int(y_positions[max(0, zc_idx - width_estimate // 2)]),
                right_base=int(y_positions[min(len(y_positions) - 1, zc_idx + width_estimate // 2)]),
                area=0.0,  # Will be calculated during deconvolution
                sigma=width_estimate / 2.355,
                is_shoulder=True,
                is_orphan=True,
            )
            shoulders.append(shoulder)

        logger.debug(f"Detected {len(shoulders)} shoulder peaks")
        return shoulders

    def _merge_peaks(
        self,
        main_peaks: list[DetectedPeakWithMatch],
        shoulder_peaks: list[DetectedPeakWithMatch],
    ) -> list[DetectedPeakWithMatch]:
        """
        Merge main peaks and shoulder peaks, avoiding duplicates.

        Args:
            main_peaks: Primary detected peaks.
            shoulder_peaks: Shoulder peaks from derivative analysis.

        Returns:
            Merged list without duplicates.
        """
        merged = list(main_peaks)

        for shoulder in shoulder_peaks:
            # Check if too close to any existing peak
            is_duplicate = any(abs(shoulder.y_position - p.y_position) < 5 for p in merged)
            if not is_duplicate:
                merged.append(shoulder)

        return merged

    def _estimate_noise(self, data: np.ndarray) -> float:
        """
        Estimate noise level using Median Absolute Deviation (MAD).

        Uses first derivative to be robust to trends.

        Args:
            data: Signal data.

        Returns:
            Estimated noise standard deviation.
        """
        if len(data) < 3:
            return 1.0

        # First derivative to remove trends
        diff = np.diff(data)

        # MAD of differences
        mad = np.median(np.abs(diff - np.median(diff)))

        # Convert MAD to std estimate (for normal distribution)
        # Scale factor: 1.4826 for normal distribution
        noise = 1.4826 * mad

        return max(noise, 1.0)  # Minimum noise of 1


def detect_peaks_in_profile(
    profile: IntensityProfile,
    params: PeakDetectionParams | None = None,
) -> list[DetectedPeakWithMatch]:
    """
    Convenience function to detect peaks in a profile.

    Args:
        profile: IntensityProfile with processed intensities.
        params: Optional detection parameters.

    Returns:
        List of DetectedPeakWithMatch objects.
    """
    detector = AdvancedPeakDetector(params)
    return detector.detect_peaks(profile)
