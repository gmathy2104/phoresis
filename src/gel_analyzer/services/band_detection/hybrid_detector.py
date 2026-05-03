"""
Hybrid band detector: CV2 primary detection + d1/d2 gap-fill.

Pipeline:
1. CV2 detects bands with clean, non-overlapping boundaries
2. Gaps between CV2 bands are identified
3. D1/d2 derivative detection runs on each gap to find faint/shoulder bands
4. Results merge with no overlap by construction

Usage:
    from gel_analyzer.services.band_detection.hybrid_detector import HybridDetector
    from gel_analyzer.services.band_detection.hybrid_params import HybridDetectionParams

    params = HybridDetectionParams(sensitivity=7, faint_bands=True)
    detector = HybridDetector(params)
    bands = detector.detect(lane_crop, lane_bbox=(x, y, w, h))
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from phoresis_core.logging_config import get_logger

from .cv2_detector import CV2BandDetector
from .hybrid_params import HybridDetectionParams
from .models import BandDetectionSource, DetectedBand

logger = get_logger(__name__)

CONTEXT_MARGIN_PX = 10
MIN_BAND_HEIGHT_PX = 3

# Loading well masking (Feature 3)
TOP_REGION_FRACTION = 0.12
VARIANCE_RATIO_THRESHOLD = 0.6
MAX_MASK_FRACTION = 0.15


@dataclass
class GapRegion:
    """A vertical gap between CV2-detected bands."""

    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


class HybridDetector:
    """Cascaded CV2 + d1/d2 band detection."""

    def __init__(self, params: HybridDetectionParams):
        self.params = params
        self.cv2_detector = CV2BandDetector(params.to_cv2_params())
        self.last_summary: dict = {}

    def detect(
        self,
        lane_crop: np.ndarray,
        lane_bbox: tuple[int, int, int, int],
        bg_type_override: str | None = None,
    ) -> list[DetectedBand]:
        """Run hybrid detection: CV2 primary + d1/d2 gap-fill."""
        t0 = time.perf_counter()

        # Resolve polarity ONCE, globally. Downstream phases reuse this
        # rather than re-detecting from their own (possibly masked) crops.
        bg_type = bg_type_override
        if bg_type not in ("light", "dark"):
            _gray = np.mean(lane_crop, axis=2) if lane_crop.ndim == 3 else lane_crop.astype(np.float64)
            _profile = _gray.mean(axis=1)
            bg_type = self.cv2_detector._detect_polarity(_profile)

        # Feature 3: loading well masking (may narrow the effective bbox).
        effective_bbox = self._compute_effective_bbox(lane_crop, lane_bbox, bg_type)
        lane_x, lane_y, lane_w, lane_h = effective_bbox

        # Crop the lane image to match the effective bbox for downstream phases.
        if effective_bbox != lane_bbox:
            mask_offset = lane_y - lane_bbox[1]
            lane_crop = lane_crop[mask_offset : mask_offset + lane_h, :]

        # Phase 1: CV2 primary (now receives effective bbox + explicit bg_type).
        cv2_bands_raw = self.cv2_detector.detect(
            lane_crop,
            effective_bbox,
            bg_type_override=bg_type,
            adaptive=self.params.adaptive_threshold,
        )
        # Merge overlapping CV2 bands so gaps are well-defined
        cv2_bands = self._merge_overlapping(cv2_bands_raw)
        # Phase 1b: split wide bands that contain doublets.
        cv2_bands = self._split_wide_bands(cv2_bands, lane_crop, effective_bbox, bg_type)
        for band in cv2_bands:
            band.detection_source = BandDetectionSource.HYBRID
            if not hasattr(band, "_hybrid_phase") or band._hybrid_phase is None:
                band._hybrid_phase = "primary"

        # Phase 2: gaps + d1/d2 gap-fill
        gaps = self._find_gaps(cv2_bands, lane_y=lane_y, lane_height=lane_h)
        gap_bands = []
        gaps_analyzed = 0
        gaps_skipped = 0

        for gap in gaps:
            if gap.size < self.params.min_gap_size_px:
                gaps_skipped += 1
                continue
            gaps_analyzed += 1
            sub_bands = self._detect_in_gap(gap, lane_crop, effective_bbox, bg_type)
            gap_bands.extend(sub_bands)

        all_bands = cv2_bands + gap_bands
        all_bands.sort(key=lambda b: b.position_y)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.last_summary = {
            "primary_bands": len(cv2_bands),
            "gap_fill_bands": len(gap_bands),
            "gaps_analyzed": gaps_analyzed,
            "gaps_skipped": gaps_skipped,
            "processing_time_ms": round(elapsed_ms, 1),
        }

        logger.info(
            f"Hybrid detection: {len(cv2_bands)} primary + {len(gap_bands)} gap-fill "
            f"= {len(all_bands)} total bands ({elapsed_ms:.0f}ms)"
        )

        return all_bands

    def _compute_effective_bbox(
        self,
        lane_crop: np.ndarray,
        lane_bbox: tuple[int, int, int, int],
        bg_type: str,
    ) -> tuple[int, int, int, int]:
        """Return bbox narrowed from the top if a loading-well region is detected.

        Polarity-aware: inverts profile for light backgrounds before peak counting.

        Reference variance is computed from the LOWER half of the lane (assumed
        quiet) rather than the full body, so that noise extending past the
        initial 12% window doesn't suppress its own detection via body variance.
        """
        from scipy.signal import find_peaks

        lane_x, lane_y, lane_w, lane_h = lane_bbox
        if not self.params.mask_loading_wells:
            return lane_bbox

        # Build 1D profile (horizontal mean across RGB).
        gray = np.mean(lane_crop, axis=2) if lane_crop.ndim == 3 else lane_crop.astype(np.float64)
        profile = gray.mean(axis=1)

        # Polarity-aware peak counting.
        profile_for_peaks = (profile.max() - profile) if bg_type == "light" else profile

        initial_top_end = max(3, int(round(TOP_REGION_FRACTION * lane_h)))
        top_region = profile[:initial_top_end]
        # Reference = lower half of lane (a known quiet zone on real gels).
        # Falls back to the post-initial-top body if lane is very short.
        ref_start = max(initial_top_end, lane_h // 2)
        reference_region = profile[ref_start:]
        if reference_region.size == 0:
            reference_region = profile[initial_top_end:]

        variance_top = float(np.var(top_region))
        variance_ref = float(np.var(reference_region)) if reference_region.size else 0.0

        prom_min = 0.1 * profile_for_peaks.max() if profile_for_peaks.max() > 0 else 1.0
        peaks_top, _ = find_peaks(profile_for_peaks[:initial_top_end], prominence=prom_min)
        peak_count_in_top = int(peaks_top.size)

        # A single prominent peak in the top region = a real band, not a
        # loading well. Skip masking.
        if peak_count_in_top == 1:
            return lane_bbox
        # Totally quiet top = nothing to mask.
        if variance_top == 0:
            return lane_bbox
        # Top quieter than the reference = not a loading well.
        if variance_ref > 0 and variance_top <= VARIANCE_RATIO_THRESHOLD * variance_ref:
            return lane_bbox

        # Decision rule hit → grow the mask until either the local region
        # quiets down or a prominent peak appears in the extension window.
        mask_hard_cap = int(round(MAX_MASK_FRACTION * lane_h))
        mask_height = initial_top_end

        while mask_height < mask_hard_cap:
            window_start = max(0, mask_height - 5)
            window_end = min(lane_h, mask_height + 5)
            local_var = float(np.var(profile[window_start:window_end]))
            # Stop growing if local region is as quiet as the reference.
            if variance_ref > 0 and local_var <= VARIANCE_RATIO_THRESHOLD * variance_ref:
                break
            if variance_ref == 0 and local_var == 0:
                break

            ahead_end = min(lane_h, mask_height + 5)
            ahead_peaks, _ = find_peaks(profile_for_peaks[mask_height:ahead_end], prominence=prom_min)
            if ahead_peaks.size > 0:
                break

            mask_height += 1

        mask_height = min(mask_height, mask_hard_cap)
        logger.info(f"[HYBRID] Lane at y={lane_y} masked top {mask_height}px (loading well)")
        return (lane_x, lane_y + mask_height, lane_w, lane_h - mask_height)

    def _merge_overlapping(self, bands: list[DetectedBand]) -> list[DetectedBand]:
        """Merge vertically overlapping bands into a single band.

        CV2 can return overlapping bboxes at high sensitivity. Merging them
        ensures gaps are well-defined for the d1/d2 gap-fill phase.
        The merged band takes the position_y, confidence, and metrics of the
        highest-confidence constituent.
        """
        if not bands:
            return bands

        sorted_bands = sorted(bands, key=lambda b: b.bbox_y)
        merged = []
        current = sorted_bands[0]

        for nxt in sorted_bands[1:]:
            current_bottom = current.bbox_y + current.bbox_height
            if nxt.bbox_y < current_bottom:
                # Overlap: extend current to cover both
                new_bottom = max(current_bottom, nxt.bbox_y + nxt.bbox_height)
                # Keep the band with higher confidence as the representative
                representative = current if current.confidence >= nxt.confidence else nxt
                current = DetectedBand(
                    position_y=representative.position_y,
                    bbox_x=min(current.bbox_x, nxt.bbox_x),
                    bbox_y=current.bbox_y,
                    bbox_width=max(current.bbox_width, nxt.bbox_width),
                    bbox_height=new_bottom - current.bbox_y,
                    confidence=representative.confidence,
                    detection_source=representative.detection_source,
                    intensity_raw=representative.intensity_raw,
                    intensity_peak=representative.intensity_peak,
                    area_pixels=representative.area_pixels,
                    peak_prominence=representative.peak_prominence,
                    peak_width_px=representative.peak_width_px,
                    snr=representative.snr,
                )
            else:
                merged.append(current)
                current = nxt

        merged.append(current)

        if len(merged) < len(bands):
            logger.debug(f"Merged {len(bands)} overlapping CV2 bands → {len(merged)} non-overlapping")

        return merged

    def _split_wide_bands(
        self,
        cv2_bands: list[DetectedBand],
        lane_crop: np.ndarray,
        lane_bbox: tuple[int, int, int, int],
        bg_type: str,
    ) -> list[DetectedBand]:
        """Split bands that contain >=2 internal peaks separated by a clean valley.

        Uses scipy.signal.find_peaks directly on the raw sub-profile — no
        ProfileProcessor, no DerivativeDetector overhead. Prominence threshold
        is relative to the local band amplitude, which is the same criterion
        the human eye uses when looking at the electropherogram.

        Polarity-aware: `bg_type` is the globally-resolved polarity (resolved
        once at the top of detect()). On light bg the profile is inverted so
        bands are maxima.

        Runs on every band (no height ratio prefilter). Prominence is the
        natural filter: singleton bands have no competing peaks to clear the
        threshold.
        """
        if not self.params.split_wide_bands or not cv2_bands:
            return cv2_bands

        from scipy.signal import find_peaks

        MIN_PROMINENCE_PCT = 0.15
        MIN_DISTANCE_PX = 3
        MIN_SUBBAND_PX = 3
        VALLEY_DEPTH_MAX = 0.75

        lane_x, lane_y, lane_w, lane_h = lane_bbox
        result: list[DetectedBand] = []

        for band in cv2_bands:
            sub_top = max(0, band.bbox_y - lane_y)
            sub_bot = min(lane_crop.shape[0], sub_top + band.bbox_height)
            # Need enough height for at least 2 sub-bands separated by a valley.
            if sub_bot - sub_top < 2 * MIN_SUBBAND_PX + 2:
                result.append(band)
                continue

            sub_crop = lane_crop[sub_top:sub_bot, :]
            # Raw profile: horizontal mean over band width. No smoothing.
            gray = np.mean(sub_crop, axis=2) if sub_crop.ndim == 3 else sub_crop.astype(np.float64)
            profile = gray.mean(axis=1).astype(np.float64)

            # Orient so bands are maxima.
            if bg_type == "light":
                profile = profile.max() - profile

            amplitude = float(profile.max() - profile.min())
            if amplitude <= 0:
                result.append(band)
                continue

            peaks, props = find_peaks(
                profile,
                prominence=MIN_PROMINENCE_PCT * amplitude,
                distance=MIN_DISTANCE_PX,
                width=(1, None),
            )

            if len(peaks) < 2:
                result.append(band)
                continue

            # For each consecutive peak pair, locate the valley and compute depth_ratio.
            valleys: list[tuple[int, float]] = []  # (y_image, depth_ratio)
            valid = True
            for i in range(len(peaks) - 1):
                left_idx = int(peaks[i])
                right_idx = int(peaks[i + 1])
                if right_idx <= left_idx:
                    valid = False
                    break
                segment = profile[left_idx : right_idx + 1]
                if segment.size == 0:
                    valid = False
                    break

                valley_local_idx = int(np.argmin(segment))
                valley_val = float(segment.min())
                left_peak_val = float(profile[left_idx])
                right_peak_val = float(profile[right_idx])
                min_peak = min(left_peak_val, right_peak_val)
                if min_peak <= 0:
                    valid = False
                    break

                depth_ratio = valley_val / min_peak  # lower = deeper valley
                if depth_ratio >= VALLEY_DEPTH_MAX:
                    logger.info(
                        f"[HYBRID-SPLIT] Rejected at y={band.bbox_y}: "
                        f"valley_depth_ratio={depth_ratio:.2f} "
                        f"(need <{VALLEY_DEPTH_MAX}), n_peaks={len(peaks)}"
                    )
                    valid = False
                    break

                # Valley position in image coordinates.
                valley_y = band.bbox_y + (left_idx + valley_local_idx)
                valleys.append((int(valley_y), float(depth_ratio)))

            if not valid or not valleys:
                result.append(band)
                continue

            # Build sub-band bounds: parent_top → valley_1 → ... → parent_bottom.
            # Adjacent sub-bands share an edge at each valley (sub1.bottom ==
            # sub2.top). The system treats touching bboxes as valid; visual
            # distinction on the gel is handled via the .gv-band-split CSS
            # class applied when metadata.hybrid_phase == 'split'.
            sub_band_bounds: list[tuple[int, int]] = []
            prev_top = band.bbox_y
            for valley_y, _ in valleys:
                sub_band_bounds.append((prev_top, valley_y))
                prev_top = valley_y
            sub_band_bounds.append((prev_top, band.bbox_y + band.bbox_height))

            # Guard: any sub-band < MIN_SUBBAND_PX → abandon split.
            if any((bot - top) < MIN_SUBBAND_PX for top, bot in sub_band_bounds):
                result.append(band)
                continue

            logger.info(
                f"[HYBRID-SPLIT] Split band at y={band.bbox_y} "
                f"(h={band.bbox_height}, amplitude={amplitude:.1f}) into "
                f"{len(sub_band_bounds)} sub-bands, "
                f"valley_depths={[round(v[1], 2) for v in valleys]}"
            )

            # Emit sub-bands.
            for i, (top, bot) in enumerate(sub_band_bounds):
                if i == 0:
                    depth_for_penalty = valleys[0][1]
                elif i == len(sub_band_bounds) - 1:
                    depth_for_penalty = valleys[-1][1]
                else:
                    depth_for_penalty = min(valleys[i - 1][1], valleys[i][1])

                penalty = 1.0 - 0.2 * depth_for_penalty
                peak_idx_local = int(peaks[i])
                position_y = band.bbox_y + peak_idx_local

                sub_band = DetectedBand(
                    position_y=position_y,
                    bbox_x=band.bbox_x,
                    bbox_y=top,
                    bbox_width=band.bbox_width,
                    bbox_height=bot - top,
                    confidence=band.confidence * penalty,
                    detection_source=BandDetectionSource.HYBRID,
                    intensity_peak=float(profile[peak_idx_local]),
                    peak_prominence=float(props["prominences"][i]),
                    peak_width_px=(float(props["widths"][i]) if "widths" in props else float(bot - top)),
                    area_pixels=int((bot - top) * band.bbox_width),
                )
                sub_band._hybrid_phase = "split"
                result.append(sub_band)

        return result

    def _find_gaps(
        self,
        cv2_bands: list[DetectedBand],
        lane_y: int,
        lane_height: int,
    ) -> list[GapRegion]:
        """Identify vertical gap regions between CV2-detected bands."""
        lane_top = lane_y
        lane_bottom = lane_y + lane_height

        sorted_bands = sorted(cv2_bands, key=lambda b: b.bbox_y)
        gaps = []
        prev_end = lane_top

        for band in sorted_bands:
            gap_start = prev_end
            gap_end = band.bbox_y
            if gap_end > gap_start:
                gaps.append(GapRegion(start=gap_start, end=gap_end))
            # Use max() to handle overlapping CV2 bands gracefully
            prev_end = max(prev_end, band.bbox_y + band.bbox_height)

        if lane_bottom > prev_end:
            gaps.append(GapRegion(start=prev_end, end=lane_bottom))

        return gaps

    def _detect_in_gap(
        self,
        gap: GapRegion,
        lane_crop: np.ndarray,
        lane_bbox: tuple[int, int, int, int],
        bg_type: str,
    ) -> list[DetectedBand]:
        """Run d1/d2 derivative detection within a gap region.

        Uses ProfileProcessor + DerivativeDetector directly. Does NOT use
        IntensityProfileExtractor or BandGeometryBuilder because both
        require a Lane Django model object — we are working with a
        sub-crop only.

        Polarity-locked: `bg_type` is the globally-resolved polarity (from
        the top of detect()) and we force `invert_profile` accordingly so
        the local ProfileProcessor cannot re-detect and flip per gap.
        """
        import dataclasses

        from .derivative_detector import DerivativeDetector
        from .profile_processor import ProfileProcessor

        lane_x, lane_y, lane_w, lane_h = lane_bbox
        invert_mode = "always" if bg_type == "light" else "never"
        d1d2_params = dataclasses.replace(
            self.params.to_derivative_params(),
            invert_profile=invert_mode,
        )

        compute_start = max(0, gap.start - CONTEXT_MARGIN_PX - lane_y)
        compute_end = min(lane_crop.shape[0], gap.end + CONTEXT_MARGIN_PX - lane_y)

        if compute_end - compute_start < d1d2_params.derivative_window:
            return []

        sub_crop = lane_crop[compute_start:compute_end, :]
        sub_y_offset = lane_y + compute_start
        sub_h = sub_crop.shape[0]

        profile = self._build_profile_from_crop(sub_crop, sub_y_offset, sub_h, lane_x, lane_w, d1d2_params)
        if not profile.raw_intensities:
            return []

        try:
            profile = ProfileProcessor(d1d2_params).process(profile)
            if not profile.processed_intensities:
                return []

            peaks, _threshold = DerivativeDetector(d1d2_params).detect(profile)
            if not peaks:
                return []
        except Exception as exc:
            logger.debug(f"Gap-fill d1/d2 failed for gap {gap.start}-{gap.end}: {exc}")
            return []

        sub_bands = self._build_bands_from_peaks(peaks, profile, lane_x, lane_w)

        clipped = []
        for band in sub_bands:
            clipped_band = self._clip_to_gap(band, gap)
            if clipped_band is not None:
                clipped_band.detection_source = BandDetectionSource.HYBRID
                clipped_band._hybrid_phase = "gap_fill"
                clipped.append(clipped_band)

        return clipped

    def _build_profile_from_crop(
        self,
        sub_crop: np.ndarray,
        sub_y_offset: int,
        sub_h: int,
        lane_x: int,
        lane_w: int,
        params,
    ):
        """Build IntensityProfile from a sub-crop without needing a Lane."""
        from .models import IntensityProfile

        if sub_crop.ndim == 3:
            gray = np.dot(sub_crop[..., :3], [0.299, 0.587, 0.114]) if sub_crop.shape[2] == 3 else sub_crop[..., 0]
        else:
            gray = sub_crop.astype(np.float64)

        margin_px = int(lane_w * (100 - params.profile_width_percent) / 200)
        x_start = max(0, margin_px)
        x_end = min(lane_w, lane_w - margin_px)
        if x_end <= x_start:
            x_start, x_end = 0, lane_w

        y_positions = list(range(sub_y_offset, sub_y_offset + sub_h))
        raw_intensities = [float(np.mean(gray[i, x_start:x_end])) for i in range(sub_h)]

        return IntensityProfile(
            y_positions=y_positions,
            raw_intensities=raw_intensities,
            lane_x=lane_x,
            lane_y=sub_y_offset,
            lane_width=lane_w,
            lane_height=sub_h,
            profile_x_start=lane_x + x_start,
            profile_x_end=lane_x + x_end,
        )

    def _build_bands_from_peaks(
        self,
        peaks,
        profile,
        lane_x: int,
        lane_w: int,
    ) -> list[DetectedBand]:
        """Convert DetectedPeak -> DetectedBand without needing a Lane."""
        bands = []
        n = len(profile.y_positions)
        if n == 0:
            return bands

        for peak in peaks:
            has_valleys = (
                peak.left_valley >= 0 and peak.right_valley >= 0 and peak.left_valley < n and peak.right_valley < n
            )
            has_bases = peak.left_base >= 0 and peak.right_base >= 0 and peak.left_base < n and peak.right_base < n

            if has_valleys and has_bases:
                valley_top = profile.y_positions[peak.left_valley]
                valley_bot = profile.y_positions[peak.right_valley]
                base_top = profile.y_positions[peak.left_base]
                base_bot = profile.y_positions[min(peak.right_base, n - 1)]
                bbox_y = max(valley_top, base_top)
                bbox_bottom = min(valley_bot, base_bot)
            elif has_valleys:
                bbox_y = profile.y_positions[peak.left_valley]
                bbox_bottom = profile.y_positions[peak.right_valley]
            elif has_bases:
                bbox_y = profile.y_positions[peak.left_base]
                bbox_bottom = profile.y_positions[min(peak.right_base, n - 1)]
            else:
                half_h = max(peak.width_px // 2, 2)
                bbox_y = peak.y_position - half_h
                bbox_bottom = peak.y_position + half_h

            bbox_height = max(bbox_bottom - bbox_y, MIN_BAND_HEIGHT_PX)

            bands.append(
                DetectedBand(
                    position_y=peak.y_position,
                    bbox_x=lane_x,
                    bbox_y=bbox_y,
                    bbox_width=lane_w,
                    bbox_height=bbox_height,
                    confidence=min(peak.snr / 10.0, 1.0) if peak.snr > 0 else 0.5,
                    detection_source=BandDetectionSource.HYBRID,
                    intensity_peak=peak.height,
                    peak_prominence=peak.prominence,
                    peak_width_px=peak.width_px,
                    snr=peak.snr,
                    area_pixels=int(bbox_height * lane_w),
                )
            )

        return bands

    def _clip_to_gap(self, band: DetectedBand, gap: GapRegion) -> DetectedBand | None:
        """Clip band to gap. Returns None if too small."""
        new_top = max(band.bbox_y, gap.start)
        new_bottom = min(band.bbox_y + band.bbox_height, gap.end)
        new_height = new_bottom - new_top

        if new_height < MIN_BAND_HEIGHT_PX:
            return None

        clipped = DetectedBand(
            position_y=band.position_y,
            bbox_x=band.bbox_x,
            bbox_y=new_top,
            bbox_width=band.bbox_width,
            bbox_height=new_height,
            polygon=band.polygon,
            confidence=band.confidence,
            detection_source=band.detection_source,
            intensity_raw=band.intensity_raw,
            intensity_peak=band.intensity_peak,
            area_pixels=int(new_height * band.bbox_width),
            peak_prominence=band.peak_prominence,
            peak_width_px=band.peak_width_px,
            snr=band.snr,
        )

        if clipped.position_y < gap.start or clipped.position_y >= gap.end:
            clipped.position_y = new_top + new_height // 2

        return clipped
