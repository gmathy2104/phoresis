"""
Derivative-based peak detection for gel electrophoresis profiles.

Inspired by chromatography software (Cobra/Chromeleon, ApexTrack/Empower)
that use 1st and 2nd derivative analysis for mathematically precise peak
identification:

- 1st derivative downward zero-crossings = peak apices
- 1st derivative upward zero-crossings = valleys
- 2nd derivative zero-crossings = inflection points = peak boundaries
- 2nd derivative local minima without d1 zero-crossing = shoulder peaks

Algorithm:
1. Get d1, d2 from profile (pre-computed by ProfileProcessor)
2. Estimate noise thresholds: noise_d1 (MAD), noise_d2 (MAD)
3. Find peak candidates: d1 downward zero-crossings with sufficient slope
4. For each peak: find nearest d2 zero-crossings on each side (boundaries)
5. Classify boundaries: baseline if boundary intensity <= threshold, else valley
6. Detect shoulders: d2 local minima below -d2_significance_factor*noise_d2 without nearby d1 zero
7. Compute area, width, SNR, prominence
8. Filter by width, SNR constraints
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from phoresis_core.logging_config import get_logger

from .models import BandDetectionParams, DetectedPeak, IntensityProfile
from .profile_processor import estimate_noise_profile

logger = get_logger(__name__)


class DerivativeDetector:
    """Derivative-based peak detection for gel electrophoresis profiles."""

    def __init__(self, params: BandDetectionParams):
        self.params = params
        self.diagnostics: dict = {}  # Populated after detect() call

    def detect(self, profile: IntensityProfile) -> tuple[list[DetectedPeak], float]:
        """Run derivative-based detection on a processed intensity profile.

        Args:
            profile: IntensityProfile with processed_intensities filled.
                     Derivatives are computed on-the-fly if not already present.

        Returns:
            Tuple of (list of DetectedPeak, threshold value used).
        """
        if not profile.processed_intensities:
            logger.warning("No processed intensities for derivative detection")
            return [], 0.0

        data = np.array(profile.processed_intensities, dtype=np.float64)

        if len(data) < 10:
            logger.warning("Profile too short for derivative detection")
            return [], 0.0

        # Ensure derivatives are available
        d1, d2 = self._get_derivatives(data, profile)

        if d1 is None or d2 is None:
            logger.warning("Could not compute derivatives")
            return [], 0.0

        # Unified baseline-aware noise estimation (signal + d1 + d2 in one pass)
        noise_profile = estimate_noise_profile(data, d1=d1, d2=d2)
        noise_d1 = noise_profile.noise_d1
        noise_d2 = noise_profile.noise_d2
        noise_signal = noise_profile.noise_signal
        baseline_count = noise_profile.baseline_count

        # Compute threshold for boundary classification
        if self.params.min_peak_height > 0:
            threshold = self.params.min_peak_height
        else:
            threshold = noise_signal * self.params.threshold_factor
            signal_max = float(np.max(data))
            if threshold > signal_max * 0.9:
                threshold = signal_max * 0.1

        # Step 1: Find peak candidates (d1 downward zero-crossings)
        # d2 must be NEGATIVE at true peaks (concave down)
        d2_threshold = noise_d2 * self.params.d2_significance_factor
        slope_threshold = noise_d1 * self.params.slope_threshold_factor

        signal_max = float(np.max(data))
        signal_min = float(np.min(data))

        logger.info(
            f"Derivative detection: noise_d1={noise_d1:.4f}, noise_d2={noise_d2:.4f}, "
            f"noise_signal={noise_signal:.2f}, threshold={threshold:.2f}, "
            f"baseline_points={baseline_count}, "
            f"baseline_pct={noise_profile.baseline_percentile:.0f}%, "
            f"fallback={noise_profile.fallback_reason or 'none'}, "
            f"d2_thresh={d2_threshold:.4f}, slope_thresh={slope_threshold:.4f}, "
            f"signal_range=[{signal_min:.1f}, {signal_max:.1f}]"
        )
        half_win = max(self.params.derivative_window // 3, 3)
        peak_indices = []
        rejected_amplitude = 0
        rejected_slope = 0
        rejected_d2 = 0
        for i in range(1, len(d1)):
            if d1[i - 1] > 0 and d1[i] <= 0:
                # Amplitude check
                if data[i] <= threshold:
                    rejected_amplitude += 1
                    continue

                # Window-based slope check — max |d1| on the rising edge
                # NOT d1[i-1] which is near zero at the crossing by definition
                slope_win_start = max(0, i - half_win)
                max_slope = float(np.max(np.abs(d1[slope_win_start : i + 1])))
                if max_slope < slope_threshold:
                    rejected_slope += 1
                    continue

                # Window-based d2 minimum search (not single-point check)
                # For asymmetric peaks, d2 min may not coincide with d1 crossing
                win_start = max(0, i - half_win)
                win_end = min(len(d2), i + half_win + 1)
                d2_min_val = float(np.min(d2[win_start:win_end]))

                # d2 must be NEGATIVE (concave down = true peak)
                # AND magnitude must exceed threshold
                if d2_min_val < -d2_threshold:
                    peak_indices.append(i)
                else:
                    rejected_d2 += 1

        total_downward_crossings = rejected_amplitude + rejected_slope + rejected_d2 + len(peak_indices)
        logger.info(
            f"Peak candidate filters: {rejected_amplitude} rejected by amplitude, "
            f"{rejected_slope} rejected by slope, {rejected_d2} rejected by d2 curvature, "
            f"{len(peak_indices)} accepted (out of {total_downward_crossings} d1 zero-crossings)"
        )

        # Step 2: Find d2 zero-crossings for inflection-point boundaries
        d2_zeros = []
        for i in range(1, len(d2)):
            if (d2[i - 1] > 0 and d2[i] <= 0) or (d2[i - 1] < 0 and d2[i] >= 0):
                d2_zeros.append(i)

        # Step 3: Detect shoulder peaks (d2 local minima without d1 zero-crossing)
        shoulders = self._find_shoulders(d1, d2, data, noise_d2, peak_indices, threshold)
        all_peak_indices = sorted(set(peak_indices + shoulders))

        # Step 4: Find valleys via d1 upward zero-crossings (d2 > 0 = concave up)
        d2_valley_threshold = noise_d2 * self.params.valley_d2_factor
        valley_indices = []
        for i in range(1, len(d1)):
            if d1[i - 1] < 0 and d1[i] >= 0:
                # Window-based d2 max (consistent with peak detection)
                vwin_start = max(0, i - half_win)
                vwin_end = min(len(d2), i + half_win + 1)
                d2_max_val = float(np.max(d2[vwin_start:vwin_end]))
                if d2_max_val > d2_valley_threshold:
                    valley_indices.append(i)

        # Always include boundaries
        valley_indices = sorted(set([0] + valley_indices + [len(data) - 1]))

        # Filter valleys by depth
        if self.params.min_valley_depth_factor > 0:
            search_range = max(self.params.min_band_width_px * 2, 20)
            min_depth = noise_signal * self.params.min_valley_depth_factor
            significant = [0]
            for vi in valley_indices[1:-1]:  # skip boundaries
                left_max = float(np.max(data[max(0, vi - search_range) : vi + 1]))
                right_max = float(np.max(data[vi : min(len(data), vi + search_range + 1)]))
                depth = min(left_max, right_max) - data[vi]
                if depth >= min_depth:
                    significant.append(vi)
            significant.append(len(data) - 1)
            valley_indices = sorted(significant)

        # Store valley indices on the profile
        profile.valley_indices = valley_indices

        logger.info(
            f"Found {len(peak_indices)} d1 peaks + {len(shoulders)} shoulders = "
            f"{len(all_peak_indices)} candidates, {len(d2_zeros)} d2 zero-crossings, "
            f"{len(valley_indices)} valleys"
        )

        # Step 5: Build DetectedPeak objects with inflection-point boundaries + valleys
        peaks = []
        rejected_width = 0
        rejected_snr = 0
        for peak_idx in all_peak_indices:
            left_bound, right_bound = self._find_inflection_boundaries(peak_idx, d2_zeros, data, threshold)

            # Find onset/offset via slope threshold for precise integration bounds
            onset, offset = self._find_peak_onset_offset(peak_idx, d1, data, slope_threshold)
            # Use onset/offset as left_base/right_base (tighter than inflection)
            left_base = onset
            right_base = offset

            # Assign valley boundaries from detected valleys
            left_v = [v for v in valley_indices if v < peak_idx]
            right_v = [v for v in valley_indices if v > peak_idx]
            left_valley = left_v[-1] if left_v else 0
            right_valley = right_v[0] if right_v else len(data) - 1

            width_px = right_bound - left_bound
            if width_px < self.params.min_band_width_px:
                rejected_width += 1
                continue
            if width_px > self.params.max_band_width_px:
                rejected_width += 1
                continue

            # Peak height (optionally refined)
            peak_height = float(data[peak_idx])
            if self.params.refine_peaks:
                _, refined_height = self._refine_peak_apex(peak_idx, data)
                peak_height = max(peak_height, refined_height)

            # Compute area via trapezoidal integration using onset/offset bounds
            seg_start = max(left_base, 0)
            seg_end = min(right_base, len(data) - 1)
            segment = data[seg_start : seg_end + 1]
            area = float(np.trapezoid(segment))

            # Prominence
            boundary_max = max(float(data[left_bound]), float(data[right_bound]))
            prominence = peak_height - boundary_max

            # SNR
            snr = peak_height / noise_signal if noise_signal > 0 else 10.0

            if snr < self.params.min_snr:
                rejected_snr += 1
                continue

            y_pos = profile.y_positions[peak_idx] if peak_idx < len(profile.y_positions) else 0

            peaks.append(
                DetectedPeak(
                    profile_index=peak_idx,
                    y_position=int(y_pos),
                    height=peak_height,
                    prominence=prominence,
                    width_px=width_px,
                    left_base=left_base,
                    right_base=right_base,
                    left_valley=left_valley,
                    right_valley=right_valley,
                    snr=snr,
                    area=area,
                )
            )

        logger.info(
            f"Derivative detection complete: {len(peaks)} peaks accepted "
            f"(rejected: {rejected_width} width, {rejected_snr} SNR)"
        )

        # Store diagnostics for API response
        self.diagnostics = {
            "profile_length": len(data),
            "signal_range": [round(signal_min, 1), round(signal_max, 1)],
            "noise": {
                "noise_d1": round(noise_d1, 4),
                "noise_d2": round(noise_d2, 4),
                "noise_signal": round(noise_signal, 2),
                "baseline_points": baseline_count,
            },
            "thresholds": {
                "amplitude": round(threshold, 2),
                "d2_curvature": round(d2_threshold, 4),
                "d2_valley": round(d2_valley_threshold, 4),
                "slope": round(slope_threshold, 4),
                "min_snr": self.params.min_snr,
            },
            "params_used": {
                "d2_significance_factor": self.params.d2_significance_factor,
                "slope_threshold_factor": self.params.slope_threshold_factor,
                "valley_d2_factor": self.params.valley_d2_factor,
                "threshold_factor": self.params.threshold_factor,
                "derivative_window": self.params.derivative_window,
                "derivative_polyorder": self.params.derivative_polyorder,
                "min_band_width_px": self.params.min_band_width_px,
                "max_band_width_px": self.params.max_band_width_px,
                "min_snr": self.params.min_snr,
            },
            "rejection_counts": {
                "d1_downward_crossings": total_downward_crossings,
                "rejected_amplitude": rejected_amplitude,
                "rejected_slope": rejected_slope,
                "rejected_d2": rejected_d2,
                "d1_peaks_accepted": len(peak_indices),
                "shoulders_found": len(shoulders),
                "total_candidates": len(all_peak_indices),
                "rejected_width": rejected_width,
                "rejected_snr": rejected_snr,
                "final_peaks": len(peaks),
            },
            "valleys": {
                "total": len(valley_indices),
                "d2_zeros": len(d2_zeros),
            },
        }

        return peaks, threshold

    def _get_derivatives(
        self,
        data: np.ndarray,
        profile: IntensityProfile,
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Get d1/d2 from profile or compute on-the-fly."""
        if profile.first_derivative and profile.second_derivative:
            return (
                np.array(profile.first_derivative, dtype=np.float64),
                np.array(profile.second_derivative, dtype=np.float64),
            )

        # Compute on-the-fly
        n = len(data)
        window = self.params.derivative_window
        polyorder = self.params.derivative_polyorder

        if n < window:
            window = n // 2
            if window % 2 == 0:
                window -= 1
            if window < 5:
                return None, None

        if polyorder >= window:
            polyorder = window - 1

        try:
            d1 = savgol_filter(data, window, polyorder, deriv=1, delta=1.0)

            d2_window = window + 6
            if d2_window % 2 == 0:
                d2_window += 1
            if d2_window > n:
                d2_window = window
            d2_polyorder = min(polyorder, d2_window - 1)

            d2 = savgol_filter(data, d2_window, d2_polyorder, deriv=2, delta=1.0)
            return d1, d2
        except ValueError as e:
            logger.warning(f"Derivative computation failed: {e}")
            return None, None

    def _estimate_baseline_noise(
        self,
        data: np.ndarray,
        d1: np.ndarray,
        d2: np.ndarray,
    ) -> tuple[float, float, int]:
        """Compatibility wrapper — kept so existing tests can call it directly.

        New code should use estimate_noise_profile() to access the full
        NoiseProfile (signal noise, baseline percentile, fallback reason).
        """
        profile = estimate_noise_profile(data, d1=d1, d2=d2)
        return profile.noise_d1, profile.noise_d2, profile.baseline_count

    def _find_shoulders(
        self,
        d1: np.ndarray,
        d2: np.ndarray,
        data: np.ndarray,
        noise_d2: float,
        existing_peaks: list[int],
        threshold: float,
    ) -> list[int]:
        """Detect shoulder peaks via d2 local minima.

        A shoulder is a d2 local minimum below -d2_significance_factor*noise_d2
        that does NOT have a d1 zero-crossing within min_band_width_px.
        """
        shoulders = []
        min_dist = self.params.min_band_width_px
        d2_threshold = -self.params.d2_significance_factor * noise_d2

        for i in range(2, len(d2) - 2):
            if d2[i] < d2_threshold and d2[i] <= d2[i - 1] and d2[i] <= d2[i + 1]:
                # Check no existing d1 peak is nearby
                too_close = any(abs(i - p) < min_dist for p in existing_peaks)
                if not too_close and data[i] > threshold:
                    shoulders.append(i)

        return shoulders

    def _find_inflection_boundaries(
        self,
        peak_idx: int,
        d2_zeros: list[int],
        data: np.ndarray,
        threshold: float,
    ) -> tuple[int, int]:
        """Find the nearest d2 zero-crossings on each side of a peak.

        Falls back to threshold crossing or half-prominence width if
        no d2 zero-crossing is found.
        """
        n = len(data)

        # Left boundary: nearest d2 zero-crossing to the left
        left_bound = 0
        for zc in reversed(d2_zeros):
            if zc < peak_idx:
                left_bound = zc
                break

        # Right boundary: nearest d2 zero-crossing to the right
        right_bound = n - 1
        for zc in d2_zeros:
            if zc > peak_idx:
                right_bound = zc
                break

        # Sanity: boundaries must not be too far
        # Clamp each side to half max_band_width_px so total stays within limit
        half_max = self.params.max_band_width_px // 2
        if peak_idx - left_bound > self.params.max_band_width_px:
            left_bound = max(0, peak_idx - half_max)
        if right_bound - peak_idx > self.params.max_band_width_px:
            right_bound = min(n - 1, peak_idx + half_max)

        return left_bound, right_bound

    def _find_peak_onset_offset(
        self,
        peak_idx: int,
        d1: np.ndarray,
        data: np.ndarray,
        slope_threshold: float,
    ) -> tuple[int, int]:
        """Find peak start (onset) and end (offset) via d1 slope threshold.

        More precise integration boundaries than d2 inflection points.
        Onset: scan left from peak until d1 drops below slope_threshold.
        Offset: scan right from peak until d1 rises above -slope_threshold.
        """
        # Onset: scan left from peak
        onset = 0
        for j in range(peak_idx - 1, -1, -1):
            if d1[j] < slope_threshold:
                onset = j
                break

        # Offset: scan right from peak
        offset = len(data) - 1
        for j in range(peak_idx + 1, len(d1)):
            if d1[j] > -slope_threshold:
                offset = j
                break

        return onset, offset

    def _refine_peak_apex(
        self,
        peak_idx: int,
        data: np.ndarray,
    ) -> tuple[float, float]:
        """Parabolic interpolation for sub-pixel peak position.

        Fits ax^2 + bx + c to 3 points around the detected apex.
        Returns refined (fractional_index, interpolated_height).
        """
        n = len(data)
        if peak_idx <= 0 or peak_idx >= n - 1:
            return float(peak_idx), float(data[peak_idx])

        y_minus = float(data[peak_idx - 1])
        y_center = float(data[peak_idx])
        y_plus = float(data[peak_idx + 1])

        denom = y_minus - 2.0 * y_center + y_plus
        if abs(denom) < 1e-10:
            return float(peak_idx), y_center

        offset = 0.5 * (y_minus - y_plus) / denom
        offset = max(-0.5, min(0.5, offset))  # clamp to +/-0.5

        refined_idx = peak_idx + offset
        refined_height = y_center - 0.25 * (y_minus - y_plus) * offset

        return refined_idx, refined_height
