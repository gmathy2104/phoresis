"""CV2 band detector using 1D intensity profile peak detection.

Extracts mean intensity per row from each lane crop, then finds peaks
in the profile using scipy.signal.find_peaks. Works identically on
both light and dark backgrounds via profile-level polarity detection.

This is the same proven approach used by ImageJ, GelAnalyzer, and PyElph.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from scipy.ndimage import binary_closing, grey_opening
from scipy.ndimage import label as ndi_label
from scipy.signal import find_peaks, peak_widths, savgol_filter
from scipy.stats import skew

from phoresis_core.logging_config import get_logger

from .cv2_params import CV2DetectionParams
from .models import BandDetectionSource, DetectedBand
from .profile_processor import estimate_noise_profile

logger = get_logger(__name__)

MAX_BANDS_PER_LANE = 50


class CV2BandDetector:
    """Detect bands in gel lane crops via 1D intensity profile analysis."""

    def __init__(self, params: CV2DetectionParams | None = None):
        self.params = params or CV2DetectionParams()

    def detect(
        self,
        lane_crop: np.ndarray,
        lane_bbox: tuple[int, int, int, int],
        bg_type_override: str | None = None,
        adaptive: bool = False,
    ) -> list[DetectedBand]:
        """Detect bands in a lane crop.

        Args:
            lane_crop: 2D image array (grayscale or RGB) of the lane region.
            lane_bbox: (x, y, width, height) of the lane in the full image.
            bg_type_override: "light", "dark", or None for auto-detection.
            adaptive: If True AND lane_h >= 30, apply zone-local adaptive
                thresholds (Feature 4) instead of the global find_peaks
                pipeline. Adds a zone-boundary component merge pass at the
                end. Default False preserves the legacy global pipeline
                bit-exactly for existing callers.

        Returns:
            List of DetectedBand with coordinates relative to the full image.
        """
        t0 = time.perf_counter()
        lane_x, lane_y, lane_w, lane_h = lane_bbox

        if lane_h < 10 or lane_w < 5:
            logger.warning(f"Lane crop too small ({lane_w}x{lane_h}), skipping")
            return []

        gray = self._normalize_to_uint8(lane_crop)

        if gray.std() < 1.0:
            logger.info("Uniform lane crop, no bands to detect")
            return []

        # Optional CLAHE for local contrast enhancement
        if self.params.clahe_enabled:
            gray = self._apply_clahe(gray)

        # === 1D PROFILE PIPELINE ===

        # Step 1: Extract mean intensity per row
        profile = self._extract_profile(gray)

        # Step 2: Smooth
        smoothing = self.params.block_size  # repurposed slider
        profile = self._smooth_profile(profile, smoothing)

        # Step 3: Detect polarity and normalize so bands = peaks
        bg_type = bg_type_override if bg_type_override in ("light", "dark") else self._detect_polarity(profile)

        if bg_type == "light":
            # Light bg: bands are dips → invert so bands become peaks
            profile = profile.max() - profile

        logger.info(
            f"[CV2-DIAG] bg={bg_type}, profile: min={profile.min():.1f}, "
            f"max={profile.max():.1f}, mean={profile.mean():.1f}"
        )

        use_adaptive = bool(adaptive) and lane_h >= 30

        if use_adaptive:
            # Adaptive zone-local threshold path (Feature 4).
            # Operates on the oriented profile so that "above threshold" means
            # "band" regardless of bg_type.
            bands_raw, corrected = self._detect_adaptive(profile, bg_type, lane_h)
            logger.info(f"[CV2-DIAG] Adaptive: {len(bands_raw)} components found (lane_h={lane_h}, zones=3)")
        else:
            # Legacy global pipeline (unchanged).
            # Step 4: Background subtraction (rolling ball on 1D)
            radius = self.params.tophat_radius  # repurposed slider
            background = self._subtract_background(profile, radius)
            corrected = np.maximum(profile - background, 0)

            # Step 5: Find peaks
            bands_raw = self._find_bands(corrected, lane_h)

            logger.info(f"[CV2-DIAG] Peaks found: {len(bands_raw)}")

        # Step 6: Build DetectedBand objects
        bands = self._build_bands(bands_raw, gray, lane_x, lane_y, lane_w, lane_h, corrected)

        if use_adaptive:
            bands = self._zone_boundary_merge(bands, lane_y, lane_h)

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            f"CV2 detection: {len(bands)} bands in {elapsed:.1f}ms "
            f"(bg={bg_type}, lane={lane_w}x{lane_h}, adaptive={use_adaptive})"
        )
        return bands

    # ----- Profile extraction -----

    def _extract_profile(self, gray: np.ndarray) -> np.ndarray:
        """Mean intensity per row → 1D profile."""
        return np.mean(gray, axis=1).astype(np.float64)

    def _smooth_profile(self, profile: np.ndarray, window: int) -> np.ndarray:
        """Savitzky-Golay smoothing on the profile."""
        if len(profile) < 7:
            return profile

        # Ensure odd window
        w = max(5, min(window, len(profile) - 1))
        if w % 2 == 0:
            w += 1

        try:
            return savgol_filter(profile, w, polyorder=2)
        except ValueError:
            return profile

    # ----- Polarity detection -----

    def _detect_polarity(self, profile: np.ndarray) -> str:
        """Detect background type from the TOP of the profile.

        The top ~15% of a gel lane is almost always empty (above all bands).
        This region shows the true background intensity regardless of how
        loaded the lane is. High intensity top = light bg. Low = dark bg.

        Falls back to skewness if the top region is ambiguous.
        """
        h = len(profile)
        top_margin = max(5, int(h * 0.10))

        # Use the top strip (above all bands) as background reference
        top_region = profile[:top_margin]
        top_median = float(np.median(top_region))

        # Also check bottom strip (below all bands)
        bottom_region = profile[-top_margin:]
        bottom_median = float(np.median(bottom_region))

        # Use the average of top and bottom edges
        bg_intensity = (top_median + bottom_median) / 2

        # Compare against the overall range
        p5 = float(np.percentile(profile, 5))
        p95 = float(np.percentile(profile, 95))
        intensity_range = p95 - p5

        if intensity_range < 5:
            # Nearly uniform — use skewness as fallback
            s = skew(profile)
            result = "light" if s < -0.1 else "dark"
            logger.info(f"[CV2-DIAG] Polarity (skew fallback): skew={s:.3f} → {result}")
            return result

        # Where does the background sit relative to the range?
        relative_bg = (bg_intensity - p5) / intensity_range

        logger.info(
            f"[CV2-DIAG] Polarity: top_median={top_median:.1f}, bottom_median={bottom_median:.1f}, "
            f"bg_intensity={bg_intensity:.1f}, range=[{p5:.1f}, {p95:.1f}], "
            f"relative_bg={relative_bg:.2%}"
        )

        # Background in upper half of range → light bg (bright background)
        # Background in lower half → dark bg (dim background)
        return "light" if relative_bg > 0.5 else "dark"

    # ----- Background subtraction -----

    def _subtract_background(self, profile: np.ndarray, radius: int) -> np.ndarray:
        """Rolling ball background estimation on 1D profile.

        Uses morphological opening (same approach as the derivative detector).
        """
        if radius * 2 >= len(profile):
            radius = max(len(profile) // 4, 5)

        size = 2 * radius + 1
        background = grey_opening(profile, size=size)
        return background

    # ----- Peak detection -----

    def _find_bands(
        self,
        corrected: np.ndarray,
        lane_h: int,
    ) -> list[tuple[int, int, float]]:
        """Find bands as peaks in the background-corrected profile.

        Returns:
            List of (y_center, height, prominence) tuples.
        """
        if corrected.max() < 1.0:
            return []

        # Unified baseline-aware noise + signal-relative floor
        noise_profile = estimate_noise_profile(corrected)
        noise = noise_profile.noise_signal

        # Prominence threshold from params (repurposed threshold_bias)
        # Lower bias = more sensitive. Scale: bias=3 → factor=0.45, bias=10 → factor=1.5
        prominence_factor = max(0.3, self.params.threshold_bias / 6.7)

        # Floor scales with the profile's dynamic range (0.5% of peak-to-peak),
        # not a hard 2.0 intensity unit — so faint gels don't get over-detected
        # and bright gels don't get under-detected.
        dynamic_range = float(corrected.max() - corrected.min())
        relative_floor = dynamic_range * 0.005
        prominence_min = max(noise * prominence_factor, relative_floor)

        # Min distance between peaks (repurposed morph_kernel)
        min_distance = max(2, self.params.morph_kernel)

        # Min peak height — very low to not miss faint bands
        # (prominence already filters noise, height is a secondary filter)
        min_height = corrected.max() * 0.01  # 1% of max peak

        logger.debug(
            f"[CV2-DIAG] Peak params: noise={noise:.2f} "
            f"(baseline_pct={noise_profile.baseline_percentile:.0f}%, "
            f"fallback={noise_profile.fallback_reason or 'none'}), "
            f"prominence_min={prominence_min:.2f} "
            f"(noise*factor={noise * prominence_factor:.2f}, "
            f"rel_floor={relative_floor:.2f}), "
            f"distance={min_distance}, min_height={min_height:.1f}"
        )

        peaks, properties = find_peaks(
            corrected,
            prominence=prominence_min,
            distance=min_distance,
            height=min_height,
        )

        if len(peaks) == 0:
            return []

        # Get peak widths at half prominence
        widths, width_heights, left_ips, right_ips = peak_widths(corrected, peaks, rel_height=0.5)

        # Build (y_center, height, prominence) list
        bands = []
        for i, peak_pos in enumerate(peaks):
            peak_height = max(3, int(np.ceil(widths[i])))
            prominence = properties["prominences"][i]
            bands.append((int(peak_pos), peak_height, float(prominence)))

        # Cap at max
        if len(bands) > MAX_BANDS_PER_LANE:
            bands.sort(key=lambda b: b[2], reverse=True)  # sort by prominence
            bands = bands[:MAX_BANDS_PER_LANE]
            bands.sort(key=lambda b: b[0])  # re-sort by position

        return bands

    # ----- Adaptive threshold per zone (Feature 4) -----

    def _detect_adaptive(
        self,
        profile: np.ndarray,
        bg_type: str,
        lane_h: int,
    ) -> tuple[list[tuple[int, int, float]], np.ndarray]:
        """Adaptive per-zone threshold detection.

        Splits the lane profile into 3 vertical zones, computes a MAD-based
        threshold per zone, applies it to build a binary band mask, smooths
        zone boundaries with a 5-px morphological close, then extracts
        connected components as bands.

        Args:
            profile: 1D oriented profile (already inverted on light bg so
                bands are maxima).
            bg_type: "light" or "dark" — kept for logging only; the profile
                has already been oriented.
            lane_h: Lane height in pixels.

        Returns:
            (bands_raw, corrected) tuple where bands_raw is a list of
            (y_center, height, prominence) tuples and corrected is the
            positive-valued signal used for confidence scaling.
        """
        N_ZONES = 3
        TRANSITION_SMOOTH_PX = 5
        SIGMA_FALLBACK_MIN = 1.0

        zone_h = lane_h // N_ZONES
        global_sigma = float(max(np.std(profile), 1e-6))
        threshold_bias = float(self.params.threshold_bias)

        # Build a local-baseline-subtracted "corrected" signal for confidence.
        corrected = np.zeros_like(profile, dtype=np.float64)
        mask = np.zeros_like(profile, dtype=bool)

        for i in range(N_ZONES):
            zstart = i * zone_h
            zend = lane_h if i == N_ZONES - 1 else (i + 1) * zone_h
            zone = profile[zstart:zend]
            if zone.size == 0:
                continue
            baseline = float(np.median(zone))
            sigma_zone = 1.4826 * float(np.median(np.abs(zone - baseline)))
            if sigma_zone < SIGMA_FALLBACK_MIN:
                sigma_zone = global_sigma
            # Scale threshold bias by the ratio of zone/global sigma. This
            # lets quieter zones use a tighter numeric threshold.
            thr_offset = threshold_bias * sigma_zone / max(global_sigma, 1e-6)
            thr = baseline + thr_offset  # above this = band (profile is oriented)
            mask[zstart:zend] = zone > thr
            # Subtract zone baseline to produce a corrected signal for
            # confidence scaling.
            corrected[zstart:zend] = np.maximum(zone - baseline, 0.0)

            logger.debug(
                f"[CV2-DIAG] zone{i} [{zstart}:{zend}] baseline={baseline:.1f} "
                f"sigma={sigma_zone:.2f} thr_offset={thr_offset:.2f}"
            )

        # Smooth zone boundary transitions with a 5-px morphological close.
        for i in range(1, N_ZONES):
            b = i * zone_h
            lo = max(0, b - TRANSITION_SMOOTH_PX)
            hi = min(lane_h, b + TRANSITION_SMOOTH_PX)
            if hi - lo >= 3:
                mask[lo:hi] = binary_closing(mask[lo:hi], structure=np.ones(3))

        # Connected components on the 1D mask.
        labeled, n_components = ndi_label(mask)
        if n_components == 0:
            return [], corrected

        bands_raw: list[tuple[int, int, float]] = []
        for comp_id in range(1, n_components + 1):
            rows = np.where(labeled == comp_id)[0]
            if rows.size == 0:
                continue
            y_start = int(rows.min())
            y_end = int(rows.max())
            height = max(3, y_end - y_start + 1)
            y_center = (y_start + y_end) // 2
            # Prominence = max corrected within the component
            prominence = float(np.max(corrected[y_start : y_end + 1]))
            if prominence <= 0:
                prominence = float(np.max(profile[y_start : y_end + 1]) - np.min(profile[y_start : y_end + 1]))
            bands_raw.append((int(y_center), int(height), float(prominence)))

        # Cap at max by prominence
        if len(bands_raw) > MAX_BANDS_PER_LANE:
            bands_raw.sort(key=lambda b: b[2], reverse=True)
            bands_raw = bands_raw[:MAX_BANDS_PER_LANE]
            bands_raw.sort(key=lambda b: b[0])

        return bands_raw, corrected

    def _zone_boundary_merge(
        self,
        bands: list[DetectedBand],
        lane_y: int,
        lane_h: int,
    ) -> list[DetectedBand]:
        """Merge pairs of bands straddling a zone boundary with tight gap.

        Pairs qualify when:
          - They straddle a zone boundary (z1, z2) expressed in image coords.
          - Vertical gap ≤ 3px.
          - Horizontal overlap ≥ 80% of the narrower bbox width.
        """
        if not bands or lane_h < 30:
            return bands

        N_ZONES = 3
        zone_h = lane_h // N_ZONES
        # Zone boundaries in image coordinates.
        boundaries = [lane_y + i * zone_h for i in range(1, N_ZONES)]

        bands_sorted = sorted(bands, key=lambda b: b.bbox_y)
        merged: list[DetectedBand] = []
        i = 0
        while i < len(bands_sorted):
            current = bands_sorted[i]
            consumed_next = False
            if i + 1 < len(bands_sorted):
                nxt = bands_sorted[i + 1]
                current_bot = current.bbox_y + current.bbox_height
                nxt_bot = nxt.bbox_y + nxt.bbox_height
                gap = nxt.bbox_y - current_bot
                straddle = any(current.bbox_y <= b <= nxt_bot for b in boundaries)
                if straddle and 0 <= gap <= 3:
                    narrow = min(current.bbox_width, nxt.bbox_width)
                    overlap = min(current.bbox_x + current.bbox_width, nxt.bbox_x + nxt.bbox_width) - max(
                        current.bbox_x, nxt.bbox_x
                    )
                    if narrow > 0 and overlap >= 0.8 * narrow:
                        new_top = min(current.bbox_y, nxt.bbox_y)
                        new_bot = max(current_bot, nxt_bot)
                        new_x = min(current.bbox_x, nxt.bbox_x)
                        new_w = (
                            max(
                                current.bbox_x + current.bbox_width,
                                nxt.bbox_x + nxt.bbox_width,
                            )
                            - new_x
                        )
                        representative = current if current.confidence >= nxt.confidence else nxt
                        merged_band = DetectedBand(
                            position_y=representative.position_y,
                            bbox_x=new_x,
                            bbox_y=new_top,
                            bbox_width=new_w,
                            bbox_height=new_bot - new_top,
                            polygon=[
                                [new_x, new_top],
                                [new_x + new_w, new_top],
                                [new_x + new_w, new_bot],
                                [new_x, new_bot],
                            ],
                            confidence=representative.confidence,
                            detection_source=representative.detection_source,
                            intensity_raw=(current.intensity_raw + nxt.intensity_raw),
                            intensity_peak=max(current.intensity_peak, nxt.intensity_peak),
                            area_pixels=int((new_bot - new_top) * new_w),
                            peak_prominence=representative.peak_prominence,
                            peak_width_px=representative.peak_width_px,
                            snr=representative.snr,
                        )
                        merged.append(merged_band)
                        i += 2
                        consumed_next = True
            if not consumed_next:
                merged.append(current)
                i += 1
        return merged

    # ----- Build DetectedBand objects -----

    def _build_bands(
        self,
        bands_raw: list[tuple[int, int, float]],
        gray: np.ndarray,
        lane_x: int,
        lane_y: int,
        lane_w: int,
        lane_h: int,
        corrected: np.ndarray,
    ) -> list[DetectedBand]:
        """Convert peak positions to DetectedBand objects."""
        float(np.mean(gray))
        corrected_max = corrected.max() if corrected.max() > 0 else 1.0

        results = []
        for y_center, band_h, prominence in bands_raw:
            half_h = band_h // 2
            y_start = max(0, y_center - half_h)
            y_end = min(gray.shape[0], y_center + half_h + 1)
            actual_h = y_end - y_start

            if actual_h < 2:
                continue

            # Intensity stats from the original grayscale lane crop
            roi = gray[y_start:y_end, :]
            intensity_raw = float(np.sum(roi))
            intensity_peak = float(np.max(roi))
            float(np.mean(roi))
            area_pixels = int(roi.size)

            # Confidence from prominence relative to max
            confidence = min(1.0, prominence / corrected_max)

            # Full-width rectangle
            polygon = [
                [lane_x, lane_y + y_start],
                [lane_x + lane_w, lane_y + y_start],
                [lane_x + lane_w, lane_y + y_end],
                [lane_x, lane_y + y_end],
            ]

            results.append(
                DetectedBand(
                    position_y=lane_y + y_center,
                    bbox_x=lane_x,
                    bbox_y=lane_y + y_start,
                    bbox_width=lane_w,
                    bbox_height=actual_h,
                    polygon=polygon,
                    confidence=confidence,
                    detection_source=BandDetectionSource.CV2_VISION,
                    intensity_raw=intensity_raw,
                    intensity_peak=intensity_peak,
                    area_pixels=area_pixels,
                )
            )

        return results

    # ----- Image preprocessing (kept from original) -----

    def _normalize_to_uint8(self, image: np.ndarray) -> np.ndarray:
        """Normalize any image dtype to uint8 grayscale."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()

        if gray.dtype == np.uint8:
            return gray

        flat = gray.ravel().astype(np.float64)
        p2 = np.percentile(flat, 2)
        p98 = np.percentile(flat, 98)

        if p98 - p2 < 1e-6:
            return np.full_like(gray, 128, dtype=np.uint8)

        clipped = np.clip(gray.astype(np.float64), p2, p98)
        normalized = ((clipped - p2) / (p98 - p2) * 255).astype(np.uint8)
        return normalized

    def _apply_clahe(self, gray: np.ndarray) -> np.ndarray:
        """Apply CLAHE local contrast enhancement."""
        h, w = gray.shape
        tile_size = max(4, min(32, h // 8))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(tile_size, tile_size))
        return clahe.apply(gray)
