"""
Calibration service for band detection parameter teaching.

Derives optimal BandDetectionParams from user-marked teaching regions
(background, small band, large band) on a gel image. This addresses
failures on heavily loaded gels where the default median-based polarity
detection confuses bands with background.

Usage:
    calibrator = DetectionCalibrator(image_array)
    result = calibrator.calibrate(background_region, small_band_region, large_band_region)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from phoresis_core.logging_config import get_logger

from .models import BandDetectionParams
from .profile_processor import estimate_noise

logger = get_logger(__name__)


@dataclass
class TeachingRegion:
    """A region marked by the user during the teaching workflow."""

    intensities: np.ndarray
    x: int
    y: int
    width: int
    height: int
    source: str = "image"  # "image" or "profile"


@dataclass
class CalibrationResult:
    """Result of the calibration process."""

    params: BandDetectionParams
    diagnostics: dict = field(default_factory=dict)
    explanations: list = field(default_factory=list)
    success: bool = True
    error: str = ""


class DetectionCalibrator:
    """
    Derives optimal band detection parameters from user-marked teaching examples.

    The user marks 3 regions on the gel image:
    - Background: a band-free area (establishes noise floor + polarity)
    - Small band: the thinnest/faintest band to detect (sets lower thresholds)
    - Large band: the widest/most intense band (sets upper thresholds)

    Any region may be None (skipped), in which case defaults are used for
    the parameters that would have been derived from that region.
    """

    def __init__(self, image: np.ndarray):
        """
        Args:
            image: Gel image as numpy array (grayscale, H×W).
        """
        self.image = image.astype(np.float64)
        self.image_height, self.image_width = image.shape[:2]

    def calibrate(
        self,
        background: TeachingRegion | None = None,
        small_band: TeachingRegion | None = None,
        large_band: TeachingRegion | None = None,
    ) -> CalibrationResult:
        """
        Derive optimal BandDetectionParams from teaching regions.

        Args:
            background: User-marked background (band-free) region.
            small_band: User-marked smallest/faintest band region.
            large_band: User-marked largest/most intense band region.

        Returns:
            CalibrationResult with derived params, diagnostics, and explanations.
        """
        if not background and not small_band and not large_band:
            return CalibrationResult(
                params=BandDetectionParams(),
                success=False,
                error="At least one teaching region must be provided.",
            )

        # Validate: small band should be smaller than large band
        if small_band and large_band and small_band.height > large_band.height:
            return CalibrationResult(
                params=BandDetectionParams(),
                success=False,
                error=(
                    f"Small band region ({small_band.height}px) is taller than "
                    f"large band region ({large_band.height}px). "
                    "Please mark the thinnest band as 'Small Band' and the widest as 'Large Band'."
                ),
            )

        diagnostics = {}
        explanations = []
        params = BandDetectionParams()

        # --- Background analysis ---
        bg_stats = self._analyze_background(background, diagnostics, explanations)

        # --- Small band analysis ---
        small_stats = self._analyze_small_band(small_band, bg_stats, params, diagnostics, explanations)

        # --- Large band analysis ---
        self._analyze_large_band(large_band, params, diagnostics, explanations)

        # --- Polarity: compare background vs band intensities directly ---
        self._determine_polarity(bg_stats, small_stats, params, diagnostics, explanations)

        # --- Derived sensitivity from SNR ---
        if small_stats and small_stats.get("snr"):
            snr = small_stats["snr"]
            # High SNR → lower sensitivity needed; low SNR → higher
            # lerp(0.80, 0.95) based on SNR: clamp SNR to [5, 50] range
            t = np.clip((snr - 5) / (50 - 5), 0.0, 1.0)
            sensitivity = 0.95 - t * (0.95 - 0.80)
            params.sensitivity = round(float(sensitivity), 2)
            explanations.append(
                f"SNR={snr:.1f} → sensitivity={params.sensitivity:.2f} (high SNR needs less sensitivity)."
            )
        else:
            explanations.append("No small band provided — keeping default sensitivity=0.85.")

        # Note which defaults were kept
        if not background:
            explanations.append("No background region provided — polarity and noise defaults kept.")
        if not small_band:
            explanations.append(
                "No small band provided — min_band_width_px, peak_prominence, min_intensity_ratio defaults kept."
            )
        if not large_band:
            explanations.append("No large band provided — max_band_width_px, rolling_ball_radius defaults kept.")

        logger.info(f"Calibration complete: {len(explanations)} explanations, params={params.to_dict()}")

        return CalibrationResult(
            params=params,
            diagnostics=diagnostics,
            explanations=explanations,
            success=True,
        )

    def _extract_roi(self, region: TeachingRegion) -> np.ndarray:
        """Extract pixel values from the image for the given region."""
        x = max(0, region.x)
        y = max(0, region.y)
        x2 = min(self.image_width, x + region.width)
        y2 = min(self.image_height, y + region.height)
        return self.image[y:y2, x:x2]

    def _row_profile(self, roi: np.ndarray) -> np.ndarray:
        """Compute row-averaged intensity profile (mean along columns)."""
        if roi.ndim == 2:
            return roi.mean(axis=1)
        return roi.ravel()

    def _analyze_background(
        self,
        background: TeachingRegion | None,
        diagnostics: dict,
        explanations: list,
    ) -> dict | None:
        """Analyze background region and derive polarity."""
        if not background:
            return None

        if background.source == "image":
            roi = self._extract_roi(background)
            pixels = roi.ravel()
        else:
            pixels = background.intensities

        bg_mean = float(np.mean(pixels))
        bg_std = float(np.std(pixels))
        bg_min = float(np.min(pixels))
        bg_max = float(np.max(pixels))

        diagnostics["background"] = {
            "mean": round(bg_mean, 1),
            "std": round(bg_std, 1),
            "range": [round(bg_min, 1), round(bg_max, 1)],
        }

        # Polarity is determined later in calibrate() by comparing
        # bg_mean against band peak intensities — the only reliable way.

        # Noise estimate
        noise = estimate_noise(pixels) if len(pixels) > 3 else bg_std
        diagnostics["noise_estimate"] = round(noise, 2)

        return {
            "mean": bg_mean,
            "std": bg_std,
            "min": bg_min,
            "max": bg_max,
            "noise": noise,
        }

    def _analyze_small_band(
        self,
        small_band: TeachingRegion | None,
        bg_stats: dict | None,
        params: BandDetectionParams,
        diagnostics: dict,
        explanations: list,
    ) -> dict | None:
        """Analyze small band region and derive lower-bound parameters."""
        if not small_band:
            return None

        if small_band.source == "image":
            roi = self._extract_roi(small_band)
            profile = self._row_profile(roi)
        else:
            profile = small_band.intensities

        peak_intensity = float(np.max(profile))
        height_px = small_band.height

        # Signal range from full image
        img_range = float(self.image.max()) - float(self.image.min())
        diagnostics["signal_range"] = round(img_range, 1)

        # SNR and prominence relative to background
        bg_mean = bg_stats["mean"] if bg_stats else float(np.percentile(self.image, 25))
        bg_std = bg_stats["std"] if bg_stats else float(np.std(self.image)) * 0.5

        snr = (abs(peak_intensity - bg_mean) / bg_std) if bg_std > 0 else 0.0
        prominence_ratio = abs(peak_intensity - bg_mean) / img_range if img_range > 0 else 0.0

        diagnostics["small_band"] = {
            "peak_intensity": round(peak_intensity, 1),
            "height_px": height_px,
            "snr": round(snr, 1),
            "prominence_ratio": round(prominence_ratio, 3),
        }

        # Derive min_band_width_px (30% tolerance below)
        params.min_band_width_px = max(3, int(height_px * 0.7))
        explanations.append(
            f"Small band height is {height_px}px — set min_band_width_px={params.min_band_width_px} (30% tolerance)."
        )

        # Derive peak_prominence (50% safety margin below small band prominence)
        if prominence_ratio > 0:
            params.peak_prominence = round(float(prominence_ratio * 0.5), 4)
            explanations.append(
                f"Small band prominence_ratio={prominence_ratio:.3f} — "
                f"set peak_prominence={params.peak_prominence:.4f} (50% safety margin)."
            )

        # Derive min_intensity_ratio
        if bg_mean > 0:
            raw_ratio = peak_intensity / bg_mean
            clamped = float(np.clip(raw_ratio * 0.7, 1.1, 5.0))
            params.min_intensity_ratio = round(clamped, 1)
            explanations.append(f"min_intensity_ratio={params.min_intensity_ratio} from small_band_peak/bg_mean × 0.7.")

        # Derive peak_distance
        params.peak_distance = max(5, height_px // 2)
        explanations.append(f"peak_distance={params.peak_distance} (half of smallest band height).")

        return {
            "peak": peak_intensity,
            "height_px": height_px,
            "snr": snr,
            "prominence_ratio": prominence_ratio,
        }

    def _analyze_large_band(
        self,
        large_band: TeachingRegion | None,
        params: BandDetectionParams,
        diagnostics: dict,
        explanations: list,
    ) -> None:
        """Analyze large band region and derive upper-bound parameters."""
        if not large_band:
            return

        if large_band.source == "image":
            roi = self._extract_roi(large_band)
            profile = self._row_profile(roi)
        else:
            profile = large_band.intensities

        peak_intensity = float(np.max(profile))
        height_px = large_band.height

        bg_mean = diagnostics.get("background", {}).get("mean", 0)
        bg_std = diagnostics.get("background", {}).get("std", 1)
        img_range = diagnostics.get("signal_range", float(self.image.max()) - float(self.image.min()))

        snr = (abs(peak_intensity - bg_mean) / bg_std) if bg_std > 0 else 0.0
        prominence_ratio = abs(peak_intensity - bg_mean) / img_range if img_range > 0 else 0.0

        diagnostics["large_band"] = {
            "peak_intensity": round(peak_intensity, 1),
            "height_px": height_px,
            "snr": round(snr, 1),
            "prominence_ratio": round(prominence_ratio, 3),
        }

        # Derive max_band_width_px (50% tolerance above)
        params.max_band_width_px = int(height_px * 1.5)
        explanations.append(
            f"Large band height is {height_px}px — set max_band_width_px={params.max_band_width_px} (50% tolerance)."
        )

        # Derive rolling_ball_radius (must be larger than biggest band)
        params.rolling_ball_radius = max(int(height_px * 2), 50)
        explanations.append(f"rolling_ball_radius={params.rolling_ball_radius} (2× largest band height, min 50).")

    def _determine_polarity(
        self,
        bg_stats: dict | None,
        small_stats: dict | None,
        params: BandDetectionParams,
        diagnostics: dict,
        explanations: list,
    ) -> None:
        """
        Determine profile inversion from background vs band intensities.

        The only reliable way: compare bg_mean against band peak intensity.
        - bg_mean < band_peak → bands are brighter → peaks point up → 'never'
        - bg_mean > band_peak → bands are darker  → need to flip  → 'always'
        """
        bg_mean = bg_stats["mean"] if bg_stats else None
        band_peak = small_stats["peak"] if small_stats else None

        # If no band peak from small_band, try large_band diagnostics
        if band_peak is None:
            lb = diagnostics.get("large_band")
            if lb:
                band_peak = lb["peak_intensity"]

        if bg_mean is not None and band_peak is not None:
            if band_peak > bg_mean:
                # Bands are brighter than background → peaks already point up
                params.invert_profile = "never"
                diagnostics["polarity"] = "bands_brighter"
                explanations.append(
                    f"Band peak ({band_peak:.0f}) > background mean "
                    f"({bg_mean:.0f}) → bands are brighter than background "
                    f"→ invert_profile='never'."
                )
            else:
                # Bands are darker than background → need to invert
                params.invert_profile = "always"
                diagnostics["polarity"] = "bands_darker"
                explanations.append(
                    f"Band peak ({band_peak:.0f}) < background mean "
                    f"({bg_mean:.0f}) → bands are darker than background "
                    f"→ invert_profile='always'."
                )
        elif bg_mean is not None:
            # No band region provided — fall back to auto
            diagnostics["polarity"] = "unknown_no_band"
            explanations.append("No band region provided — keeping invert_profile='auto'.")
        else:
            # No background either
            diagnostics["polarity"] = "unknown_no_bg"
