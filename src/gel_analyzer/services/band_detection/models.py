"""
Dataclasses for band detection parameters, intermediate results, and outputs.

This module defines the data structures used throughout the band detection pipeline:
- BandDetectionParams: User-configurable detection parameters
- IntensityProfile: 1D intensity profile extracted from a lane
- DetectedPeak: A detected peak in the intensity profile
- DetectedBand: A detected band with full geometry and metrics
- BandDetectionResult: Complete result for a lane
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BackgroundMethod(StrEnum):
    """Background subtraction methods for intensity profile processing."""

    ROLLING_BALL = "rolling_ball"
    MORPHOLOGICAL = "morphological"
    TOP_HAT = "top_hat"
    LINEAR_BASELINE = "linear_baseline"
    NONE = "none"


class BandDetectionSource(StrEnum):
    """Source of band detection."""

    AUTO = "CV2"
    CV2_VISION = "CV2V"
    MANUAL = "MANUAL"
    YOLO = "YOLO"
    SAM = "SAM"
    HYBRID = "HYBRID"


# Reference image height for pixel-based parameter calibration.
# Default params (max_band_width_px=80, rolling_ball_radius=50, etc.)
# are tuned for images ~800px tall. Larger images need proportionally
# scaled values via BandDetectionParams.scaled().
REFERENCE_HEIGHT = 800


@dataclass
class BandDetectionParams:
    """
    Parameters for the band detection algorithm.

    All parameters can be tuned by the user via the API and frontend.
    Defaults are permissive (favour recall over precision) so users see
    detected bands immediately and can tighten thresholds as needed.

    Detection is performed by DerivativeDetector (chromatography-style
    d1/d2 zero-crossing analysis).  The deprecated parameters below are
    retained only for the legacy PeakDetector path used by
    _detect_ladder_guided().
    """

    # --- Preprocessing (ProfileExtractor / ProfileProcessor / Service) ---
    smoothing_window: int = 7  # SG smoothing window (odd). Lower = less smoothing, more peaks
    smoothing_polyorder: int = 3  # SG polynomial order for smoothing
    background_method: BackgroundMethod = BackgroundMethod.ROLLING_BALL
    rolling_ball_radius: int = 50  # Rolling ball / morph / tophat radius
    profile_width_percent: float = 50.0  # % of lane width to sample for profile
    lane_edge_margin_percent: float = 0.0  # % of lane height to exclude from top/bottom
    invert_profile: str = "auto"  # "auto", "always", "never"
    clahe_enabled: bool = True  # CLAHE contrast enhancement before detection

    # --- Derivative-based detection (DerivativeDetector) ---
    d2_significance_factor: float = 1.5  # d2 noise multiplier (higher = stricter curvature check)
    slope_threshold_factor: float = 1.0  # d1 noise multiplier (eliminates flat/drift crossings)
    min_snr: float = 1.0  # Minimum signal-to-noise ratio for peak acceptance
    threshold_factor: float = 1.5  # Auto-threshold multiplier (noise × factor)
    min_peak_height: float = 0.0  # Manual threshold; 0 = auto
    min_valley_depth_factor: float = 1.0  # Valley depth for splitting overlapping peaks (noise × factor)
    valley_d2_factor: float = 1.5  # Multiplier on noise_d2 for the d2 valley threshold (splits overlapping peaks)
    min_band_width_px: int = 5  # Min band width in pixels (narrower = noise); raised from 3 in 2026-04 noise cleanup
    max_band_width_px: int = 120  # Max band width in pixels (wider = smear/artifact)
    derivative_window: int = 15  # SG window for d1/d2 computation (odd, >= 7)
    derivative_polyorder: int = 4  # SG poly order for derivatives (>= 2 for d2; 4 recommended)
    show_derivatives: bool = False  # Compute & return d1/d2 arrays to frontend
    refine_peaks: bool = True  # Parabolic sub-pixel apex refinement

    # --- DEPRECATED: used only by legacy PeakDetector (ladder-guided path) ---
    sensitivity: float = 0.85
    peak_prominence: float = 0.01
    peak_distance: int = 10
    min_intensity_ratio: float = 1.5
    integration_method: str = "derivative"  # Always "derivative"; kept for DB compat

    def __post_init__(self):
        """Validate and auto-correct parameters."""
        # Validate invert_profile
        if self.invert_profile not in ("auto", "always", "never"):
            raise ValueError("invert_profile must be 'auto', 'always', or 'never'")

        # Validate derivative_window (must be odd, >= 7)
        if self.derivative_window < 7:
            self.derivative_window = 7
        if self.derivative_window % 2 == 0:
            self.derivative_window += 1

        # Validate derivative_polyorder (must be >= 2 and < derivative_window)
        if self.derivative_polyorder < 2:
            self.derivative_polyorder = 2
        if self.derivative_polyorder >= self.derivative_window:
            self.derivative_polyorder = self.derivative_window - 1

        # Validate threshold_factor
        if self.threshold_factor < 0.5:
            self.threshold_factor = 0.5

        # Validate min_valley_depth_factor
        if self.min_valley_depth_factor < 0.0:
            self.min_valley_depth_factor = 0.0

        # Validate d2_significance_factor
        if self.d2_significance_factor < 1.0:
            self.d2_significance_factor = 1.0
        elif self.d2_significance_factor > 8.0:
            self.d2_significance_factor = 8.0

        # Validate slope_threshold_factor
        if self.slope_threshold_factor < 0.5:
            self.slope_threshold_factor = 0.5
        elif self.slope_threshold_factor > 5.0:
            self.slope_threshold_factor = 5.0

        # Validate valley_d2_factor
        if self.valley_d2_factor < 0.5:
            self.valley_d2_factor = 0.5
        elif self.valley_d2_factor > 5.0:
            self.valley_d2_factor = 5.0

        # Validate min_snr
        if self.min_snr < 0.5:
            self.min_snr = 0.5
        elif self.min_snr > 10.0:
            self.min_snr = 10.0

        # Smoothing window must be odd
        if self.smoothing_window % 2 == 0:
            self.smoothing_window += 1

        # Polyorder must be less than window
        if self.smoothing_polyorder >= self.smoothing_window:
            self.smoothing_polyorder = self.smoothing_window - 1

        # Lane edge margin sanity check
        if not 0.0 <= self.lane_edge_margin_percent <= 40.0:
            raise ValueError("lane_edge_margin_percent must be between 0 and 40")

        # Profile width sanity check
        if not 10.0 <= self.profile_width_percent <= 100.0:
            raise ValueError("profile_width_percent must be between 10 and 100")

        # Convert string to enum if needed
        if isinstance(self.background_method, str):
            self.background_method = BackgroundMethod(self.background_method)

        # Auto-correct deprecated integration_method values
        if self.integration_method != "derivative":
            self.integration_method = "derivative"

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses and storage.

        Does NOT include deprecated params (sensitivity, peak_prominence,
        peak_distance, min_intensity_ratio, integration_method).
        """
        return {
            # Preprocessing
            "smoothing_window": self.smoothing_window,
            "smoothing_polyorder": self.smoothing_polyorder,
            "background_method": self.background_method.value,
            "rolling_ball_radius": self.rolling_ball_radius,
            "profile_width_percent": self.profile_width_percent,
            "lane_edge_margin_percent": self.lane_edge_margin_percent,
            "invert_profile": self.invert_profile,
            "clahe_enabled": self.clahe_enabled,
            # Derivative detection
            "d2_significance_factor": self.d2_significance_factor,
            "slope_threshold_factor": self.slope_threshold_factor,
            "min_snr": self.min_snr,
            "threshold_factor": self.threshold_factor,
            "min_peak_height": self.min_peak_height,
            "min_valley_depth_factor": self.min_valley_depth_factor,
            "valley_d2_factor": self.valley_d2_factor,
            "min_band_width_px": self.min_band_width_px,
            "max_band_width_px": self.max_band_width_px,
            "derivative_window": self.derivative_window,
            "derivative_polyorder": self.derivative_polyorder,
            "show_derivatives": self.show_derivatives,
            "refine_peaks": self.refine_peaks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BandDetectionParams:
        """Create from dictionary (API request or storage)."""
        if not data:
            return cls()

        # Handle background_method conversion
        if "background_method" in data and isinstance(data["background_method"], str):
            data = data.copy()
            data["background_method"] = BackgroundMethod(data["background_method"])

        # Filter to only active fields (deprecated params are excluded)
        valid_fields = {
            # Preprocessing
            "smoothing_window",
            "smoothing_polyorder",
            "background_method",
            "rolling_ball_radius",
            "profile_width_percent",
            "lane_edge_margin_percent",
            "invert_profile",
            "clahe_enabled",
            # Derivative detection
            "d2_significance_factor",
            "slope_threshold_factor",
            "min_snr",
            "threshold_factor",
            "min_peak_height",
            "min_valley_depth_factor",
            "valley_d2_factor",
            "min_band_width_px",
            "max_band_width_px",
            "derivative_window",
            "derivative_polyorder",
            "show_derivatives",
            "refine_peaks",
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)

    def scaled(self, image_height: int) -> BandDetectionParams:
        """Return a copy with pixel-based values scaled for the given image height.

        Default parameters are calibrated for ~800px images. For larger images
        (e.g. Bio-Rad SCN at 1638px), pixel thresholds like max_band_width_px
        and rolling_ball_radius must scale proportionally to avoid rejecting
        legitimate bands or under-fitting background.

        Scaled (pixel-based): min/max_band_width_px, rolling_ball_radius, peak_distance.
        NOT scaled (relative): d2_significance_factor, slope_threshold_factor,
        min_snr, threshold_factor, profile_width_percent, smoothing_window, etc.

        Args:
            image_height: Height of the image in pixels.

        Returns:
            New BandDetectionParams with scaled pixel values, or self if
            within 15% of REFERENCE_HEIGHT (deadband to avoid unnecessary copies).
        """
        if image_height <= 0:
            return self

        scale = image_height / REFERENCE_HEIGHT

        # No scaling needed if within 15% of reference
        if 0.85 <= scale <= 1.15:
            return self

        return BandDetectionParams(
            # Preprocessing (NOT scaled — resolution-independent)
            smoothing_window=self.smoothing_window,
            smoothing_polyorder=self.smoothing_polyorder,
            background_method=self.background_method,
            rolling_ball_radius=max(20, int(round(self.rolling_ball_radius * scale))),
            profile_width_percent=self.profile_width_percent,
            lane_edge_margin_percent=self.lane_edge_margin_percent,
            invert_profile=self.invert_profile,
            clahe_enabled=self.clahe_enabled,
            # Derivative detection — pixel params scale, relative params don't
            d2_significance_factor=self.d2_significance_factor,
            slope_threshold_factor=self.slope_threshold_factor,
            min_snr=self.min_snr,
            threshold_factor=self.threshold_factor,
            min_peak_height=self.min_peak_height,
            min_valley_depth_factor=self.min_valley_depth_factor,
            valley_d2_factor=self.valley_d2_factor,
            min_band_width_px=max(2, int(round(self.min_band_width_px * scale))),
            max_band_width_px=max(20, int(round(self.max_band_width_px * scale))),
            derivative_window=self.derivative_window,
            derivative_polyorder=self.derivative_polyorder,
            show_derivatives=self.show_derivatives,
            refine_peaks=self.refine_peaks,
            # Deprecated — pass through for legacy PeakDetector (ladder-guided)
            sensitivity=self.sensitivity,
            peak_prominence=self.peak_prominence,
            peak_distance=max(5, int(round(self.peak_distance * scale))),
            min_intensity_ratio=self.min_intensity_ratio,
        )


@dataclass
class IntensityProfile:
    """
    1D intensity profile extracted from a gel lane.

    The profile represents the averaged pixel intensity at each Y position
    along the lane, from top (well) to bottom (dye front).

    Attributes:
        y_positions: Y positions in image coordinates (pixels from top).
        raw_intensities: Raw averaged intensity values at each Y position.
        processed_intensities: Intensities after smoothing and background
                              subtraction. Filled by ProfileProcessor.
        background: Estimated background signal at each Y position.
        lane_x: X coordinate of lane top-left corner.
        lane_y: Y coordinate of lane top-left corner.
        lane_width: Lane width in pixels.
        lane_height: Lane height in pixels.
        profile_x_start: X start of the profile extraction window.
        profile_x_end: X end of the profile extraction window.
    """

    y_positions: list[int] = field(default_factory=list)
    raw_intensities: list[float] = field(default_factory=list)
    processed_intensities: list[float] = field(default_factory=list)
    background: list[float] = field(default_factory=list)
    lane_x: int = 0
    lane_y: int = 0
    lane_width: int = 0
    lane_height: int = 0
    profile_x_start: int = 0
    profile_x_end: int = 0
    was_inverted: bool = False
    valley_indices: list[int] = field(default_factory=list)  # profile indices of all valleys
    first_derivative: list[float] = field(default_factory=list)
    second_derivative: list[float] = field(default_factory=list)
    derivative_zero_crossings: list[dict] = field(default_factory=list)
    # Each dict: {"index": int, "type": "peak"|"valley"|"inflection"|"shoulder", "derivative": 1|2, "intensity": float}

    def __len__(self) -> int:
        return len(self.y_positions)

    @property
    def is_empty(self) -> bool:
        """Check if profile has data."""
        return len(self.y_positions) == 0

    @property
    def signal_range(self) -> float:
        """Get the range of processed intensities."""
        if not self.processed_intensities:
            return 0.0
        return max(self.processed_intensities) - min(self.processed_intensities)


@dataclass
class DetectedPeak:
    """
    A detected peak in the intensity profile.

    Represents a potential band before geometry construction.

    Attributes:
        profile_index: Index into IntensityProfile arrays.
        y_position: Y position in image coordinates (pixels).
        height: Peak height (intensity value at peak).
        prominence: Peak prominence (height above surrounding baseline).
        width_px: Peak width in pixels at half prominence.
        left_base: Left edge index in profile.
        right_base: Right edge index in profile.
        snr: Signal-to-noise ratio.
        area: Integrated area under the peak curve.
    """

    profile_index: int
    y_position: int
    height: float
    prominence: float
    width_px: int
    left_base: int
    right_base: int
    left_valley: int = -1  # profile index of left valley (local minimum)
    right_valley: int = -1  # profile index of right valley (local minimum)
    snr: float = 0.0
    area: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "profile_index": self.profile_index,
            "y_position": self.y_position,
            "height": self.height,
            "prominence": self.prominence,
            "width_px": self.width_px,
            "left_base": self.left_base,
            "right_base": self.right_base,
            "left_valley": self.left_valley,
            "right_valley": self.right_valley,
            "snr": self.snr,
            "area": self.area,
        }


@dataclass
class DetectedBand:
    """
    A detected band with full geometry and quantification metrics.

    Ready to be converted to a Band Django model instance.

    Attributes:
        position_y: Center Y position in image coordinates.
        bbox_x: Bounding box X (left edge).
        bbox_y: Bounding box Y (top edge).
        bbox_width: Bounding box width.
        bbox_height: Bounding box height.
        polygon: Polygon points [[x1,y1], [x2,y2], ...] for refined segmentation.
        confidence: Detection confidence (0-1) based on SNR and peak quality.
        detection_source: Source of detection (AUTO = d1/d2 derivative).
        intensity_raw: Sum of pixel intensities in band region.
        intensity_peak: Peak intensity value.
        area_pixels: Number of pixels in band region.
        peak_prominence: Peak prominence from scipy.signal.
        peak_width_px: Peak width from scipy.signal.
        snr: Signal-to-noise ratio.
    """

    position_y: int
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    polygon: list[list[int]] = field(default_factory=list)
    confidence: float = 0.0
    detection_source: BandDetectionSource = BandDetectionSource.AUTO
    intensity_raw: float = 0.0
    intensity_peak: float = 0.0
    area_pixels: int = 0
    peak_prominence: float = 0.0
    peak_width_px: int = 0
    snr: float = 0.0
    left_boundary_type: str = ""  # "baseline" or "valley"
    right_boundary_type: str = ""  # "baseline" or "valley"
    integrated_area: float = 0.0  # Area from peak integration

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        result = {
            "position_y": self.position_y,
            "bbox_x": self.bbox_x,
            "bbox_y": self.bbox_y,
            "bbox_width": self.bbox_width,
            "bbox_height": self.bbox_height,
            "polygon": self.polygon,
            "confidence": round(self.confidence, 3),
            "detection_source": self.detection_source.value,
            "intensity_raw": round(self.intensity_raw, 2),
            "intensity_peak": round(self.intensity_peak, 2),
            "area_pixels": self.area_pixels,
            "peak_prominence": round(self.peak_prominence, 2),
            "peak_width_px": self.peak_width_px,
            "snr": round(self.snr, 2),
        }
        if self.left_boundary_type:
            result["left_boundary_type"] = self.left_boundary_type
            result["right_boundary_type"] = self.right_boundary_type
            result["integrated_area"] = round(self.integrated_area, 2)
        return result


@dataclass
class BandDetectionResult:
    """
    Complete result of band detection for a lane.

    Contains all detected bands plus metadata about the detection process.

    Attributes:
        lane_id: Database ID of the Lane model.
        lane_number: Lane number (1-indexed from left).
        bands: List of detected bands.
        profile: The intensity profile used for detection.
        params_used: Detection parameters that were applied.
        success: Whether detection completed successfully.
        error_message: Error message if detection failed.
        processing_time_ms: Time taken for detection in milliseconds.
    """

    lane_id: int
    lane_number: int
    bands: list[DetectedBand] = field(default_factory=list)
    profile: IntensityProfile | None = None
    params_used: BandDetectionParams | None = None
    success: bool = True
    error_message: str = ""
    processing_time_ms: float = 0.0
    threshold_used: float = 0.0
    detection_diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        result = {
            "lane_id": self.lane_id,
            "lane_number": self.lane_number,
            "bands": [b.to_dict() for b in self.bands],
            "band_count": len(self.bands),
            "success": self.success,
            "error_message": self.error_message,
            "processing_time_ms": round(self.processing_time_ms, 1),
        }
        if self.detection_diagnostics:
            result["diagnostics"] = self.detection_diagnostics
        return result
