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
from scipy.ndimage import grey_dilation, grey_erosion, grey_opening
from scipy.ndimage import label as ndi_label
from scipy.signal import find_peaks, peak_widths, savgol_coeffs, savgol_filter
from scipy.stats import skew

from phoresis_core.logging_config import get_logger

from .cv2_params import CV2DetectionParams
from .models import BandDetectionSource, DetectedBand

logger = get_logger(__name__)

MAX_BANDS_PER_LANE = 50

# Scale of the noise term of _find_bands' prominence threshold. With the honest
# noise (_row_noise), 2 x the historical factor puts the hybrid's bias 10 (factor
# 1.49) at ~3 sigma of the smoothed profile's noise; the owner chose this scale over
# 1 x on two real gels, 2026-09-27 - 1 x made the panel MORE permissive in dense lanes.
PROMINENCE_NOISE_SCALE = 2.0


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
                end. Either way the lane gets the lane-wide CLAHE tiles and
                the profile clipped to its data (_clip_to_local_data): the
                adaptive call kept the historical tiles and smoothing until
                2026-09-27, and their phantom bands with them (_apply_clahe).

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

        use_adaptive = bool(adaptive) and lane_h >= 30

        # Optional CLAHE for local contrast enhancement
        if self.params.clahe_enabled:
            gray = self._apply_clahe(gray)

        # === 1D PROFILE PIPELINE ===

        # Step 1: Extract mean intensity per row
        profile = self._extract_profile(gray)
        # Kept as extracted: the global pipeline measures its noise on it (_find_bands).
        raw_profile = profile

        # Step 2: Smooth, kept within the range of the raw rows around each point
        smoothing = self.params.block_size  # repurposed slider
        profile = self._clip_to_local_data(self._smooth_profile(raw_profile, smoothing), raw_profile)

        # Step 3: Detect polarity and normalize so bands = peaks
        bg_type = bg_type_override if bg_type_override in ("light", "dark") else self._detect_polarity(profile)

        if bg_type == "light":
            # Light bg: bands are dips → invert so bands become peaks
            profile = profile.max() - profile

        logger.info(
            f"[CV2-DIAG] bg={bg_type}, profile: min={profile.min():.1f}, "
            f"max={profile.max():.1f}, mean={profile.mean():.1f}"
        )

        if use_adaptive:
            # Adaptive zone-local threshold path (Feature 4).
            # Operates on the oriented profile so that "above threshold" means
            # "band" regardless of bg_type.
            bands_raw, corrected = self._detect_adaptive(profile, bg_type, lane_h)
            logger.info(f"[CV2-DIAG] Adaptive: {len(bands_raw)} bands found (lane_h={lane_h}, zones=3)")
        else:
            # Global pipeline: the CV2 panel, the hybrid with adaptive off, and
            # an adaptive call on a lane under 30 rows.
            # Step 4: Background subtraction (rolling ball on 1D)
            radius = self.params.tophat_radius  # repurposed slider
            background = self._subtract_background(profile, radius)
            corrected = np.maximum(profile - background, 0)

            # Step 5: Find peaks
            bands_raw = self._find_bands(corrected, lane_h, raw_profile=raw_profile)

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

    @staticmethod
    def _clip_to_local_data(smoothed: np.ndarray, raw: np.ndarray, reach: int = 5) -> np.ndarray:
        """Keep the smoothed profile within the range of the raw samples around it.

        Savitzky-Golay (order 2, window = block_size, often several band widths)
        overshoots beside a sharp band - once the profile is oriented bands-up, a
        dip below the lane background on each side - and drags close bands into
        each other. The rolling-ball opening followed those dips down, so the
        plain background between two bands stood above its own estimate and came
        out as a band: the phantom in the gap, since the 1D rewrite ec50a5c12.
        Bounded by the min and max of the `reach` raw samples around each point,
        the smoothing can no longer invent a value no nearby row has; where it
        stays inside that range (noise on a flat background) it is untouched.
        """
        if len(raw) < 7:
            return smoothed
        return np.clip(smoothed, grey_erosion(raw, size=reach), grey_dilation(raw, size=reach))

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
        raw_profile: np.ndarray | None = None,
    ) -> list[tuple[int, int, float]]:
        """Find bands as peaks in the background-corrected profile.

        The noise term of the prominence threshold is NOT measured on `corrected`:
        `max(profile - opening, 0)` is zero-clipped, most of its samples are exactly
        0 on a clean lane, so a noise estimate on it came out ~0 (or deflated), the
        0.5 % floor governed every lane and threshold_bias had no effect.

        Args:
            corrected: background-subtracted, oriented profile (bands = peaks).
            lane_h: lane height in pixels.
            raw_profile: the row profile as extracted, before smoothing, background
                subtraction and clipping; the noise is measured on it (_row_noise),
                carried through detect()'s smoothing. A direct caller that omits it
                hands an unclipped profile: the noise is measured on `corrected`.

        Returns:
            List of (y_center, height, prominence) tuples.
        """
        if corrected.max() < 1.0:
            return []

        if raw_profile is not None:
            noise = self._row_noise(raw_profile, smoothing_window=self.params.block_size)
        else:
            noise = self._row_noise(corrected)

        # Prominence threshold from params (repurposed threshold_bias)
        # Lower bias = more sensitive. Scale: bias=3 → factor=0.45, bias=10 → factor=1.5
        prominence_factor = max(0.3, self.params.threshold_bias / 6.7)

        # Floor scales with the profile's dynamic range (0.5% of peak-to-peak),
        # not a hard 2.0 intensity unit — so faint gels don't get over-detected
        # and bright gels don't get under-detected.
        dynamic_range = float(corrected.max() - corrected.min())
        relative_floor = dynamic_range * 0.005
        noise_term = PROMINENCE_NOISE_SCALE * noise * prominence_factor
        prominence_min = max(noise_term, relative_floor)

        # Min distance between peaks (repurposed morph_kernel)
        min_distance = max(2, self.params.morph_kernel)

        # Min peak height — very low to not miss faint bands
        # (prominence already filters noise, height is a secondary filter)
        min_height = corrected.max() * 0.01  # 1% of max peak

        logger.debug(
            f"[CV2-DIAG] Peak params: noise={noise:.2f} "
            f"(on {'raw profile' if raw_profile is not None else 'corrected'}), "
            f"prominence_min={prominence_min:.2f} "
            f"(scale*noise*factor={noise_term:.2f}, "
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

    @staticmethod
    def _row_noise(profile: np.ndarray, smoothing_window: int | None = None) -> float:
        """Row noise sigma of a profile, from its first differences.

        MAD of the differences, scaled to a sigma per row: a slope or a band barely
        moves a median of differences, so the estimate stays honest on a loaded
        lane. With `smoothing_window`, the sigma is carried through the smoothing
        _smooth_profile applies with that window (same window rule), times the
        filter's white-noise gain: the peaks are read on the smoothed profile. A
        profile under 7 rows is left unsmoothed there, so its gain is 1.
        """
        d = np.diff(profile)
        sigma = 1.4826 * float(np.median(np.abs(d - np.median(d)))) / np.sqrt(2)
        if smoothing_window is None or len(profile) < 7:
            return sigma
        w = max(5, min(smoothing_window, len(profile) - 1))
        if w % 2 == 0:
            w += 1
        return sigma * float(np.sqrt(np.sum(savgol_coeffs(w, 2) ** 2)))

    # ----- Adaptive threshold per zone (Feature 4) -----

    def _detect_adaptive(
        self,
        profile: np.ndarray,
        bg_type: str,
        lane_h: int,
    ) -> tuple[list[tuple[int, int, float]], np.ndarray]:
        """Adaptive per-zone threshold detection.

        Splits the lane profile into 3 vertical zones and takes a baseline
        (median) and a MAD-based threshold offset per zone, both interpolated
        linearly between the zone centres: the threshold moves smoothly down
        the lane. Until 2026-09-27 it stepped at each zone border, and a band
        sitting on a border was cut in two by the step, its centre off by up
        to 10 px; the 5-px morphological close at the borders, now gone, did
        not rejoin it.

        The rows above threshold form runs (connected components), and the
        bands are the profile's peaks inside each run, found once on the whole
        oriented profile with the local offset as minimum prominence. A
        doublet or a packed ladder is one run above threshold but several
        peaks: taking one band per run merged them into a single band at the
        run's midpoint. A band sits at its peak row, as high as its FWHM (3
        rows at least); a run with no peak inside (a slope running off the
        lane end, a bump too shallow for the local prominence) keeps one band
        at its maximum, as high as the run. At a lane end on a sloped
        background that band is a phantom on the last rows; dropping it where
        the run touches the lane end was measured on 11 real gels on
        2026-09-27 and rejected: it also drops the real last ladder band of a
        lane that ends on it.

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
        SIGMA_FALLBACK_MIN = 1.0

        zone_h = lane_h // N_ZONES
        global_sigma = float(max(np.std(profile), 1e-6))
        threshold_bias = float(self.params.threshold_bias)

        centres: list[float] = []
        baselines: list[float] = []
        offsets: list[float] = []
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
            centres.append((zstart + zend - 1) / 2.0)
            baselines.append(baseline)
            offsets.append(thr_offset)

            logger.debug(
                f"[CV2-DIAG] zone{i} [{zstart}:{zend}] baseline={baseline:.1f} "
                f"sigma={sigma_zone:.2f} thr_offset={thr_offset:.2f}"
            )

        # Baseline and offset per row, linear between the zone centres (flat
        # beyond the outer ones): no step left at a zone border to cut a band.
        # Above baseline + offset = band (the profile is oriented); the signal
        # above the baseline scales the confidence.
        rows_all = np.arange(len(profile))
        base_y = np.interp(rows_all, centres, baselines)
        off_y = np.interp(rows_all, centres, offsets)
        mask = profile > base_y + off_y
        corrected = np.maximum(profile - base_y, 0.0)

        # The peaks, found once on the whole profile, each at least as
        # prominent as the local offset; their FWHM is the band height.
        peaks, _ = find_peaks(profile, prominence=np.maximum(off_y, 1e-6), distance=max(2, self.params.morph_kernel))
        fwhm = peak_widths(profile, peaks, rel_height=0.5)[0] if peaks.size else np.array([])

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
            # One band per peak inside the run: a doublet or a packed ladder is
            # one run above threshold but several peaks.
            inside = np.where((peaks >= y_start) & (peaks <= y_end))[0]
            if inside.size:
                run_bands = [(int(peaks[j]), max(3, int(np.ceil(fwhm[j])))) for j in inside]
            else:
                y_max = y_start + int(np.argmax(profile[y_start : y_end + 1]))
                run_bands = [(y_max, max(3, y_end - y_start + 1))]
            for y_center, height in run_bands:
                # Prominence = the signal above the local baseline at the band row
                prominence = float(corrected[y_center])
                if prominence <= 0:
                    prominence = float(np.ptp(profile[y_start : y_end + 1]))
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

        With the zone threshold interpolated (2026-09-27) there is no step left
        to cut a band, yet this still merges on real gels: 18 pairs over 11 gels,
        none on the synthetic grid. Measured then, it is neutral - without it,
        one more real ladder band and two more phantoms - so it stays.
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

            # Intensity stats from the grayscale lane crop, CLAHE'd when enabled
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
        """Normalize any image dtype to uint8 grayscale.

        A 16-bit lane crop is stretched between its OWN 2nd and 98th percentiles,
        so an empty lane's background mottling gets full contrast. A range shared
        by the gel (whole image, union of the lane boxes, or a fixed /257) was
        measured on 11 real gels on 2026-09-27 and rejected by the owner: about
        10 fewer detections over 5 empty lanes, for 2 to 9 real ladder bands lost.
        """
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
        """Apply CLAHE local contrast enhancement, one tile across the lane, 8 down.

        `tileGridSize` is a tile COUNT (columns, rows). The historical grid,
        min(32, h // 8) each way, cut an 80-px lane into ~2.5-px columns and
        rows a 25th-32nd of its height: a tile of near-flat background has a
        histogram a grey level or two wide, and equalising it turned a one-level
        step in a band's tail into a 7-level one, a phantom band ~38 px either
        side of the real one. The global pipeline has used the lane-wide tiles
        since aeda84d0; the adaptive path kept the historical grid until
        2026-09-27, as its absolute zone thresholds counted on the stretch to
        lift faint bands - the owner validated the lane-wide tiles on both
        paths on 11 real gels.
        """
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(1, 8))
        return clahe.apply(gray)
