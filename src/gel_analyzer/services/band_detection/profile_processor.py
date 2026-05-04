"""
Signal processing for intensity profiles.

Implements smoothing and background subtraction to prepare profiles
for peak detection. Uses Savitzky-Golay filtering which preserves
peak shapes better than simple moving averages.

Reference: Savitzky-Golay filter preserves higher moments of the data
and is ideal for analytical chemistry signals like gel intensity profiles.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import grey_opening, white_tophat
from scipy.signal import savgol_filter
from scipy.stats import skew

from phoresis_core.logging_config import get_logger

from .models import BackgroundMethod, BandDetectionParams, IntensityProfile

logger = get_logger(__name__)


def detect_image_polarity(image: np.ndarray) -> str:
    """Determine if image has bright background requiring profile inversion.

    Uses the TOP and BOTTOM image strips as background reference — the
    first/last rows of a gel image are essentially always outside the lanes
    (gel frame or empty paper), so they show the true background intensity
    regardless of how the bands are distributed.

    Previous implementation used the full-image median vs p2..p98 range,
    which got fooled on dark-bg gels with bright artefacts (annotations,
    saturated borders, white calibration markings etc.) — the median could
    drift above 0.6 and wrongly trigger inversion.

    Returns:
        "always" if bright background detected (needs inversion)
        "never" if dark background detected (no inversion)
        "auto" if ambiguous (fall through to lane-level heuristics)
    """
    img = np.asarray(image)
    if img.ndim == 3:
        img = np.mean(img, axis=2)
    img = img.astype(np.float64)

    h = img.shape[0]
    strip = max(5, int(h * 0.05))  # top/bottom 5% of image rows

    top_strip = img[:strip]
    bottom_strip = img[-strip:]
    edge_median = float(np.median(np.concatenate([top_strip.ravel(), bottom_strip.ravel()])))

    # Trimmed p5..p95 for range — excludes outlier pixels
    flat = img.ravel()
    p5 = float(np.percentile(flat, 5))
    p95 = float(np.percentile(flat, 95))
    trimmed_range = p95 - p5

    if trimmed_range < 5:
        # Nearly uniform image — can't distinguish, let lane-level decide
        return "auto"

    relative_bg = (edge_median - p5) / trimmed_range

    logger.info(
        f"Image polarity (top+bottom strips): edge_median={edge_median:.1f}, "
        f"p5={p5:.1f}, p95={p95:.1f}, range={trimmed_range:.1f}, "
        f"relative_bg={relative_bg:.2%}"
    )

    if relative_bg > 0.6:  # Bright background at image edges → light bg
        return "always"
    if relative_bg < 0.4:  # Dark background at image edges → dark bg
        return "never"
    return "auto"  # Ambiguous → fall through to lane heuristics


class ProfileProcessor:
    """
    Process intensity profiles: smoothing and background subtraction.

    Pipeline:
    1. Savitzky-Golay smoothing (reduces noise while preserving peak shape)
    2. Background estimation (rolling ball, morphological, or linear)
    3. Background subtraction

    Usage:
        processor = ProfileProcessor(params)
        processed_profile = processor.process(profile)
    """

    def __init__(self, params: BandDetectionParams):
        """
        Initialize processor with detection parameters.

        Args:
            params: Detection parameters controlling smoothing and background.
        """
        self.params = params

    def process(self, profile: IntensityProfile) -> IntensityProfile:
        """
        Apply smoothing and background subtraction to profile.

        Modifies profile in place, filling processed_intensities and background.

        Args:
            profile: IntensityProfile with raw_intensities.

        Returns:
            Same profile with processed_intensities filled.
        """
        if not profile.raw_intensities:
            logger.warning("Empty profile, skipping processing")
            return profile

        # Guardrail: if rolling_ball_radius < max_band_width_px, the ball can
        # fit inside large bands and the estimated background starts tracking
        # the band itself, flattening true peaks.
        if (
            self.params.background_method == BackgroundMethod.ROLLING_BALL
            and self.params.rolling_ball_radius < self.params.max_band_width_px
        ):
            logger.warning(
                f"[ProfileProcessor] rolling_ball_radius={self.params.rolling_ball_radius} "
                f"< max_band_width_px={self.params.max_band_width_px} — "
                f"risk of flattening wide bands. Recommend "
                f">= {int(self.params.max_band_width_px * 1.5)} "
                f"(1.5× max band width)."
            )

        raw = np.array(profile.raw_intensities, dtype=np.float64)

        logger.info(
            f"Profile processing: {len(raw)} points, "
            f"dtype_range=[{raw.min():.1f}, {raw.max():.1f}], "
            f"mean={raw.mean():.1f}, std={raw.std():.1f}"
        )

        # Step 1: Apply Savitzky-Golay smoothing
        smoothed = self._apply_smoothing(raw)

        # Step 2: Detect and correct polarity (for dark-on-light images)
        smoothed, was_inverted = self._detect_and_correct_polarity(smoothed)

        logger.info(f"After polarity: inverted={was_inverted}, range=[{smoothed.min():.1f}, {smoothed.max():.1f}]")

        # Step 3: Estimate and subtract background
        background = self._estimate_background(smoothed)
        corrected = smoothed - background

        # Ensure non-negative (background subtraction can produce negatives)
        pre_clip_min = corrected.min()
        corrected = np.maximum(corrected, 0)

        logger.info(
            f"After background ({self.params.background_method.value}): "
            f"bg_range=[{background.min():.1f}, {background.max():.1f}], "
            f"signal_range=[{corrected.min():.1f}, {corrected.max():.1f}], "
            f"pre_clip_min={pre_clip_min:.1f}, "
            f"peak_to_peak={np.ptp(corrected):.1f}"
        )

        # Update profile
        profile.processed_intensities = corrected.tolist()
        profile.background = background.tolist()
        profile.was_inverted = was_inverted

        # Always compute derivatives (required by DerivativeDetector)
        self._compute_derivatives(profile)

        return profile

    def _detect_and_correct_polarity(self, data: np.ndarray) -> tuple[np.ndarray, bool]:
        """
        Detect if profile has inverted polarity (dark bands on light background)
        and invert the signal if needed so that bands appear as peaks.

        Uses TOP + BOTTOM strips as background reference (same approach as
        CV2BandDetector._detect_polarity). The outermost 10% of a lane is
        almost always empty — above/below all bands — so those regions show
        the true background intensity regardless of band density elsewhere.

        Pure skewness (previous implementation) got fooled on dark-bg gels
        with a large empty top region: the long tail of low values gave a
        negative skew and wrongly triggered inversion. The strip-based
        heuristic is independent of the spatial distribution of bands inside
        the lane.

        Args:
            data: Smoothed intensity data.

        Returns:
            Tuple of (possibly inverted data, whether inversion was applied).
        """
        mode = self.params.invert_profile

        if mode == "never":
            logger.info("Polarity: mode='never', skipping detection")
            return data, False
        if mode == "always":
            logger.info("Polarity: mode='always', forcing inversion")
            return data.max() - data, True

        # --- Auto-detect ---
        h = len(data)
        strip = max(5, int(h * 0.10))

        top_median = float(np.median(data[:strip]))
        bottom_median = float(np.median(data[-strip:]))
        bg_intensity = (top_median + bottom_median) / 2

        # Trimmed range: p5..p95 ignores pixel-level outliers on 16-bit images.
        p5 = float(np.percentile(data, 5))
        p95 = float(np.percentile(data, 95))
        intensity_range = p95 - p5

        if intensity_range < 5:
            # Nearly uniform profile — fall back to skewness on the whole lane.
            s = skew(data)
            should_invert = s < -0.1
            logger.info(
                f"Polarity (skew fallback, uniform profile): skew={s:.3f} → {'LIGHT' if should_invert else 'DARK'} bg"
            )
            if should_invert:
                return data.max() - data, True
            return data, False

        # Background sits in the upper half of the trimmed range → light bg.
        # Background sits in the lower half → dark bg.
        relative_bg = (bg_intensity - p5) / intensity_range

        logger.info(
            f"Polarity auto-detect (top+bottom strips): "
            f"top_median={top_median:.1f}, bottom_median={bottom_median:.1f}, "
            f"bg_intensity={bg_intensity:.1f}, p5={p5:.1f}, p95={p95:.1f}, "
            f"relative_bg={relative_bg:.2%} → "
            f"{'LIGHT (INVERT)' if relative_bg > 0.5 else 'DARK (no invert)'}"
        )

        if relative_bg > 0.5:
            return data.max() - data, True
        return data, False

    def _apply_smoothing(self, data: np.ndarray) -> np.ndarray:
        """
        Apply Savitzky-Golay smoothing filter.

        The Savitzky-Golay filter fits a polynomial to a sliding window,
        which smooths noise while preserving peak shapes and heights
        better than simple moving averages.

        Args:
            data: Raw intensity data.

        Returns:
            Smoothed intensity data.
        """
        window = self.params.smoothing_window
        polyorder = self.params.smoothing_polyorder

        # Adjust window if data is too short
        if len(data) < window:
            window = len(data) // 2
            if window % 2 == 0:
                window -= 1
            if window < 3:
                logger.warning("Data too short for smoothing, returning as-is")
                return data.copy()

        # Ensure window is odd
        if window % 2 == 0:
            window += 1

        # Ensure polyorder < window
        if polyorder >= window:
            polyorder = window - 1

        try:
            smoothed = savgol_filter(data, window, polyorder)
            logger.debug(f"Applied Savitzky-Golay: window={window}, polyorder={polyorder}")
            return smoothed
        except ValueError as e:
            logger.warning(f"Savitzky-Golay failed: {e}, returning original")
            return data.copy()

    def _estimate_background(self, data: np.ndarray) -> np.ndarray:
        """
        Estimate background signal using configured method.

        Args:
            data: Smoothed intensity data.

        Returns:
            Estimated background array.
        """
        method = self.params.background_method

        if method == BackgroundMethod.NONE:
            return np.zeros_like(data)

        elif method == BackgroundMethod.ROLLING_BALL:
            return self._rolling_ball_background(data)

        elif method == BackgroundMethod.MORPHOLOGICAL:
            return self._morphological_background(data)

        elif method == BackgroundMethod.TOP_HAT:
            # Top-hat returns foreground, so we compute background indirectly
            tophat = self._tophat_filter(data)
            return data - tophat

        elif method == BackgroundMethod.LINEAR_BASELINE:
            return self._linear_baseline(data)

        else:
            logger.warning(f"Unknown background method: {method}, using none")
            return np.zeros_like(data)

    def _rolling_ball_background(self, data: np.ndarray) -> np.ndarray:
        """
        Rolling ball algorithm for background estimation.

        Conceptually, imagines a ball rolling along the underside of the
        signal curve. The trace of the ball's center defines the background.
        Implemented using morphological opening with a large structuring element.

        Args:
            data: Smoothed intensity data.

        Returns:
            Background estimate.
        """
        radius = self.params.rolling_ball_radius

        # Adjust radius if larger than data
        if radius * 2 >= len(data):
            radius = max(len(data) // 4, 5)
            logger.debug(f"Adjusted rolling ball radius to {radius}")

        size = 2 * radius + 1

        # Morphological opening approximates rolling ball
        # Opening = erosion followed by dilation
        background = grey_opening(data, size=size)

        logger.debug(f"Rolling ball background: radius={radius}")
        return background

    def _morphological_background(self, data: np.ndarray) -> np.ndarray:
        """
        Simple morphological opening for background estimation.

        Similar to rolling ball but uses a flat structuring element.

        Args:
            data: Smoothed intensity data.

        Returns:
            Background estimate.
        """
        radius = self.params.rolling_ball_radius

        if radius * 2 >= len(data):
            radius = max(len(data) // 4, 5)

        size = 2 * radius + 1

        background = grey_opening(data, size=size)
        logger.debug(f"Morphological background: size={size}")

        return background

    def _tophat_filter(self, data: np.ndarray) -> np.ndarray:
        """
        White top-hat transform (detects peaks on varying background).

        Top-hat = original - opening = peaks only
        This is useful when you want the peaks directly rather than
        the background.

        Args:
            data: Smoothed intensity data.

        Returns:
            Peaks (foreground) extracted by top-hat.
        """
        radius = self.params.rolling_ball_radius

        if radius * 2 >= len(data):
            radius = max(len(data) // 4, 5)

        size = 2 * radius + 1

        tophat = white_tophat(data, size=size)
        logger.debug(f"Top-hat filter: size={size}")

        return tophat

    def _linear_baseline(self, data: np.ndarray) -> np.ndarray:
        """
        Linear baseline connecting first and last points.

        Simple approach suitable for gels with uniform background
        that increases or decreases linearly along the lane.

        Args:
            data: Smoothed intensity data.

        Returns:
            Linear baseline.
        """
        n = len(data)
        baseline = np.linspace(data[0], data[-1], n)
        logger.debug("Applied linear baseline")
        return baseline

    def _compute_derivatives(self, profile: IntensityProfile) -> None:
        """Compute 1st and 2nd derivatives using Savitzky-Golay filter.

        Populates profile.first_derivative, profile.second_derivative,
        and profile.derivative_zero_crossings.

        Args:
            profile: IntensityProfile with processed_intensities filled.
        """
        if not profile.processed_intensities:
            return

        data = np.array(profile.processed_intensities, dtype=np.float64)
        n = len(data)

        window = self.params.derivative_window
        polyorder = self.params.derivative_polyorder

        # Ensure window fits data
        if n < window:
            window = n // 2
            if window % 2 == 0:
                window -= 1
            if window < 5:
                logger.warning("Profile too short for derivative computation")
                return

        # Ensure polyorder < window
        if polyorder >= window:
            polyorder = window - 1

        try:
            d1 = savgol_filter(data, window, polyorder, deriv=1, delta=1.0)

            # Use wider window for d2 to suppress noise amplification
            d2_window = window + 6
            if d2_window % 2 == 0:
                d2_window += 1
            if d2_window > n:
                d2_window = window  # Fall back to same window
            d2_polyorder = min(polyorder, d2_window - 1)

            d2 = savgol_filter(data, d2_window, d2_polyorder, deriv=2, delta=1.0)

        except ValueError as e:
            logger.warning(f"Derivative computation failed: {e}")
            return

        profile.first_derivative = d1.tolist()
        profile.second_derivative = d2.tolist()
        profile.derivative_zero_crossings = self._find_zero_crossings(d1, d2, data)

        logger.info(
            f"Derivatives computed: d1_range=[{d1.min():.4f}, {d1.max():.4f}], "
            f"d2_range=[{d2.min():.4f}, {d2.max():.4f}], "
            f"zero_crossings={len(profile.derivative_zero_crossings)}"
        )

    def _find_zero_crossings(
        self,
        d1: np.ndarray,
        d2: np.ndarray,
        data: np.ndarray,
    ) -> list[dict]:
        """Find zero-crossings in d1 and d2 for visualization markers.

        Args:
            d1: First derivative array.
            d2: Second derivative array.
            data: Original processed intensity data.

        Returns:
            List of marker dicts with index, type, derivative, intensity.
        """
        markers = []

        # Noise from baseline regions (consistent with DerivativeDetector)
        p25 = np.percentile(data, 25)
        baseline_mask = data <= p25
        baseline_idx = np.where(baseline_mask)[0]
        if len(baseline_idx) >= 20:
            d2_bl = d2[baseline_idx]
            noise_d2 = 1.4826 * float(np.median(np.abs(d2_bl - np.median(d2_bl))))
        else:
            noise_d2 = 1.4826 * float(np.median(np.abs(d2 - np.median(d2))))
        noise_d2 = max(noise_d2, 1e-10)

        # Use 1.5x for visualization markers (lower than detection threshold)
        d2_threshold = noise_d2 * 1.5

        # d1 zero-crossings — use correct d2 sign convention:
        # peaks: d2 < 0 (concave down), valleys: d2 > 0 (concave up)
        for i in range(1, len(d1)):
            if d1[i - 1] > 0 and d1[i] <= 0:
                # Downward zero-crossing → peak apex (d2 must be negative)
                d2_val = d2[i] if i < len(d2) else 0
                if d2_val < -d2_threshold:
                    markers.append(
                        {
                            "index": i,
                            "type": "peak",
                            "derivative": 1,
                            "intensity": round(float(data[i]), 2),
                        }
                    )
            elif d1[i - 1] < 0 and d1[i] >= 0:
                # Upward zero-crossing → valley (d2 must be positive)
                d2_val = d2[i] if i < len(d2) else 0
                if d2_val > d2_threshold:
                    markers.append(
                        {
                            "index": i,
                            "type": "valley",
                            "derivative": 1,
                            "intensity": round(float(data[i]), 2),
                        }
                    )

        # Merge close peak markers to prevent split visualization
        merge_dist = self.params.min_band_width_px
        peak_markers = [m for m in markers if m["type"] == "peak"]
        other_markers = [m for m in markers if m["type"] != "peak"]
        if len(peak_markers) > 1:
            peak_markers = self._merge_close_markers(peak_markers, merge_dist)
        markers = peak_markers + other_markers

        # d2 zero-crossings → inflection points
        for i in range(1, len(d2)):
            if (d2[i - 1] > 0 and d2[i] <= 0) or (d2[i - 1] < 0 and d2[i] >= 0):
                markers.append(
                    {
                        "index": i,
                        "type": "inflection",
                        "derivative": 2,
                        "intensity": round(float(data[i]), 2),
                    }
                )

        return markers

    def _merge_close_markers(self, markers: list[dict], merge_dist: int) -> list[dict]:
        """Merge peak markers within merge_dist, keeping the highest intensity."""
        if len(markers) <= 1:
            return markers

        sorted_markers = sorted(markers, key=lambda m: m["index"])
        merged = []
        cluster = [sorted_markers[0]]

        for m in sorted_markers[1:]:
            if m["index"] - cluster[-1]["index"] <= merge_dist:
                cluster.append(m)
            else:
                best = max(cluster, key=lambda c: c["intensity"])
                merged.append(best)
                cluster = [m]

        best = max(cluster, key=lambda c: c["intensity"])
        merged.append(best)

        return merged


def estimate_noise(data: np.ndarray) -> float:
    """
    Estimate noise level using Median Absolute Deviation (MAD).

    MAD is more robust than standard deviation for signals with peaks,
    as peaks don't significantly affect the median.

    The first derivative is used to remove slow trends before
    computing MAD.

    Args:
        data: Signal data.

    Returns:
        Estimated noise standard deviation.
    """
    if len(data) < 3:
        return 0.0

    # First derivative to remove slow trends
    diff = np.diff(data)

    # MAD of differences
    mad = np.median(np.abs(diff - np.median(diff)))

    # Convert MAD to standard deviation estimate
    # For normal distribution: sigma = 1.4826 * MAD
    noise = 1.4826 * mad

    return float(noise)


@dataclass
class NoiseProfile:
    """Unified noise characterization for a single 1D profile.

    Returned by estimate_noise_profile(). All MAD values are scaled by
    1.4826 to approximate Gaussian sigma. A floor of 1e-10 is applied
    to avoid division-by-zero on synthetic flat signals.

    Attributes:
        noise_signal: MAD of the intensity signal in the baseline region.
        noise_d1: MAD of the first derivative in the baseline region (0 if
            d1 was not provided).
        noise_d2: MAD of the second derivative in the baseline region (0 if
            d2 was not provided).
        baseline_count: Number of profile samples classified as baseline.
        baseline_percentile: The intensity percentile used as the baseline
            cutoff — 25 for band-dense profiles, 50 for sparse profiles.
        fallback_reason: None if the baseline region was used; otherwise a
            short tag describing the fallback path ("too_few_baseline",
            "flat_signal").
    """

    noise_signal: float
    noise_d1: float
    noise_d2: float
    baseline_count: int
    baseline_percentile: float
    fallback_reason: str | None = None


def estimate_noise_profile(
    data: np.ndarray,
    d1: np.ndarray | None = None,
    d2: np.ndarray | None = None,
    sparse_profile_skew_threshold: float = 1.0,
) -> NoiseProfile:
    """Unified baseline-aware noise estimation for a 1D profile.

    Profiles are expected to be polarity-corrected (bands-as-peaks). For
    this regime:
      - A sparse profile (1-2 tall peaks, most samples at baseline) produces
        a long positive tail → high positive skew (>> 1).
      - A dense profile (many peaks covering a big fraction of the profile)
        produces a near-bimodal distribution → skew near zero.

    Baseline percentile is picked on that basis:
      - 50% if skew > sparse_profile_skew_threshold (sparse: plenty of true
        baseline samples exist below the median).
      - 25% otherwise (dense: the median is inside bands, so only the
        lower quartile is reliable baseline).

    Falls back to full-signal MAD with fallback_reason="too_few_baseline"
    when the baseline region has < 20 points (e.g. very short profile).
    Falls back with fallback_reason="flat_signal" when max(data)-min(data)
    < 5 (signal is too uniform to reliably separate bands from background).

    Args:
        data: 1D intensity profile (polarity-corrected, bands-as-peaks).
        d1: Optional first derivative. If None, noise_d1 is 0.
        d2: Optional second derivative. If None, noise_d2 is 0.
        sparse_profile_skew_threshold: Skew cutoff for sparse classification.
            Profiles with skew above this threshold use the 50% baseline
            percentile. Default 1.0 separates 1-2 peak profiles (skew ~4)
            from dense multi-peak profiles (skew < 1).

    Returns:
        NoiseProfile with MAD-based noise estimates scaled by 1.4826.
    """
    n = len(data)

    if n < 80:
        noise_signal = 1.4826 * float(np.median(np.abs(data - np.median(data))))
        noise_d1_ = 1.4826 * float(np.median(np.abs(d1 - np.median(d1)))) if d1 is not None else 0.0
        noise_d2_ = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) if d2 is not None else 0.0
        return NoiseProfile(
            noise_signal=max(noise_signal, 1e-10),
            noise_d1=max(noise_d1_, 1e-10) if d1 is not None else 0.0,
            noise_d2=max(noise_d2_, 1e-10) if d2 is not None else 0.0,
            baseline_count=0,
            baseline_percentile=0.0,
            fallback_reason="too_few_baseline",
        )

    data_range = float(np.max(data) - np.min(data))
    if data_range < 5.0:
        noise_signal = 1.4826 * float(np.median(np.abs(data - np.median(data))))
        noise_d1_ = 1.4826 * float(np.median(np.abs(d1 - np.median(d1)))) if d1 is not None else 0.0
        noise_d2_ = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) if d2 is not None else 0.0
        return NoiseProfile(
            noise_signal=max(noise_signal, 1e-10),
            noise_d1=max(noise_d1_, 1e-10) if d1 is not None else 0.0,
            noise_d2=max(noise_d2_, 1e-10) if d2 is not None else 0.0,
            baseline_count=0,
            baseline_percentile=0.0,
            fallback_reason="flat_signal",
        )

    s = float(skew(data))
    percentile = 50.0 if s > sparse_profile_skew_threshold else 25.0
    cutoff = np.percentile(data, percentile)
    baseline_mask = data <= cutoff
    baseline_indices = np.where(baseline_mask)[0]

    if len(baseline_indices) < 20:
        noise_signal = 1.4826 * float(np.median(np.abs(data - np.median(data))))
        noise_d1_ = 1.4826 * float(np.median(np.abs(d1 - np.median(d1)))) if d1 is not None else 0.0
        noise_d2_ = 1.4826 * float(np.median(np.abs(d2 - np.median(d2)))) if d2 is not None else 0.0
        return NoiseProfile(
            noise_signal=max(noise_signal, 1e-10),
            noise_d1=max(noise_d1_, 1e-10) if d1 is not None else 0.0,
            noise_d2=max(noise_d2_, 1e-10) if d2 is not None else 0.0,
            baseline_count=len(baseline_indices),
            baseline_percentile=percentile,
            fallback_reason="too_few_baseline",
        )

    signal_bl = data[baseline_indices]
    noise_signal = 1.4826 * float(np.median(np.abs(signal_bl - np.median(signal_bl))))

    if d1 is not None:
        d1_bl = d1[baseline_indices]
        noise_d1_ = 1.4826 * float(np.median(np.abs(d1_bl - np.median(d1_bl))))
    else:
        noise_d1_ = 0.0

    if d2 is not None:
        d2_bl = d2[baseline_indices]
        noise_d2_ = 1.4826 * float(np.median(np.abs(d2_bl - np.median(d2_bl))))
    else:
        noise_d2_ = 0.0

    return NoiseProfile(
        noise_signal=max(noise_signal, 1e-10),
        noise_d1=max(noise_d1_, 1e-10) if d1 is not None else 0.0,
        noise_d2=max(noise_d2_, 1e-10) if d2 is not None else 0.0,
        baseline_count=len(baseline_indices),
        baseline_percentile=percentile,
        fallback_reason=None,
    )
