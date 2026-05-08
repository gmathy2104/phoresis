"""
Dataclasses for densitometry service parameters and results.

This module defines the data structures used throughout the densitometry pipeline:
- DensitometryParams: User-configurable analysis parameters
- PeakIntegrationResult: Result of Gaussian fitting for a single band
- LaneDensitometryResultData: Complete densitometry data for a lane
- DensitometryAnalysisResult: Full analysis results for an analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NormalizationMethod(StrEnum):
    """Normalization methods for relative quantification."""

    LANE_TOTAL = "lane_total"
    GEL_TOTAL = "gel_total"
    LOADING_CONTROL = "loading_control"
    REFERENCE_BAND = "reference_band"


class BackgroundMethodDensitometry(StrEnum):
    """Background subtraction methods for densitometry."""

    ROLLING_BALL = "rolling_ball"
    LOCAL_MINIMA = "local_minima"
    LINEAR_BASELINE = "linear_baseline"
    NONE = "none"


@dataclass
class DensitometryParams:
    """
    Parameters for densitometry analysis.

    Controls Gaussian fitting, background correction, and normalization.

    Attributes:
        gaussian_fit_enabled: Whether to fit Gaussian curves to peaks
        background_method: Method for background subtraction
        normalization_method: Method for relative quantification
        smoothing_window: Savitzky-Golay filter window size
        smoothing_polyorder: Polynomial order for smoothing
        rolling_ball_radius: Radius for rolling ball background
        min_peak_area: Minimum area threshold for valid peaks
        min_fit_r_squared: Minimum R-squared for valid Gaussian fit
        profile_width_percent: Percentage of lane width for profile extraction
        integration_method: 'gaussian' (fitted) or 'trapezoid' (raw)
    """

    gaussian_fit_enabled: bool = True
    background_method: BackgroundMethodDensitometry = BackgroundMethodDensitometry.ROLLING_BALL
    normalization_method: NormalizationMethod = NormalizationMethod.LANE_TOTAL
    smoothing_window: int = 11
    smoothing_polyorder: int = 3
    rolling_ball_radius: int = 50
    min_peak_area: float = 100.0
    min_fit_r_squared: float = 0.7
    profile_width_percent: float = 50.0
    integration_method: str = "gaussian"  # 'gaussian' or 'trapezoid'

    # Reference band for LOADING_CONTROL or REFERENCE_BAND normalization
    reference_band_id: str | None = None

    # Profile correction flag - if True, profile is already background-corrected
    # by ProfileProcessor, so PeakIntegrator should NOT subtract background again
    profile_already_corrected: bool = True

    def __post_init__(self):
        """Validate and auto-correct parameters."""
        # Smoothing window must be odd
        if self.smoothing_window % 2 == 0:
            self.smoothing_window += 1

        # Polyorder must be less than window
        if self.smoothing_polyorder >= self.smoothing_window:
            self.smoothing_polyorder = self.smoothing_window - 1

        # Profile width sanity check
        if not 10.0 <= self.profile_width_percent <= 100.0:
            self.profile_width_percent = max(10.0, min(100.0, self.profile_width_percent))

        # Convert string to enum if needed
        if isinstance(self.background_method, str):
            self.background_method = BackgroundMethodDensitometry(self.background_method)
        if isinstance(self.normalization_method, str):
            self.normalization_method = NormalizationMethod(self.normalization_method)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses and storage."""
        return {
            "gaussian_fit_enabled": self.gaussian_fit_enabled,
            "background_method": self.background_method.value,
            "normalization_method": self.normalization_method.value,
            "smoothing_window": self.smoothing_window,
            "smoothing_polyorder": self.smoothing_polyorder,
            "rolling_ball_radius": self.rolling_ball_radius,
            "min_peak_area": self.min_peak_area,
            "min_fit_r_squared": self.min_fit_r_squared,
            "profile_width_percent": self.profile_width_percent,
            "integration_method": self.integration_method,
            "reference_band_id": self.reference_band_id,
            "profile_already_corrected": self.profile_already_corrected,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DensitometryParams:
        """Create from dictionary (API request or storage)."""
        if not data:
            return cls()

        # Handle enum conversions
        data = data.copy()
        if "background_method" in data and isinstance(data["background_method"], str):
            data["background_method"] = BackgroundMethodDensitometry(data["background_method"])
        if "normalization_method" in data and isinstance(data["normalization_method"], str):
            data["normalization_method"] = NormalizationMethod(data["normalization_method"])

        # Filter to only valid fields
        valid_fields = {
            "gaussian_fit_enabled",
            "background_method",
            "normalization_method",
            "smoothing_window",
            "smoothing_polyorder",
            "rolling_ball_radius",
            "min_peak_area",
            "min_fit_r_squared",
            "profile_width_percent",
            "integration_method",
            "reference_band_id",
            "profile_already_corrected",
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)


@dataclass
class PeakDetectionParams:
    """
    Parameters for automatic peak detection from intensity profiles.

    Controls peak finding algorithm, shoulder detection, and deconvolution.

    Attributes:
        sensitivity: Detection sensitivity (0-1). Higher = more peaks detected.
        min_peak_distance: Minimum distance between peaks in pixels.
        min_prominence: Minimum peak prominence as fraction of signal range.
        min_width_px: Minimum peak width in pixels.
        max_width_px: Maximum peak width in pixels.
        enable_shoulder_detection: Detect shoulders using second derivative.
        enable_deconvolution: Attempt multi-Gaussian deconvolution for wide peaks.
        deconvolution_threshold_px: Only deconvolve peaks wider than this.
        match_tolerance_px: Tolerance for matching peaks to existing bands.
    """

    sensitivity: float = 0.85
    min_peak_distance: int = 10
    min_prominence: float = 0.02
    min_width_px: int = 3
    max_width_px: int = 100
    enable_shoulder_detection: bool = True
    enable_deconvolution: bool = False
    deconvolution_threshold_px: int = 40
    match_tolerance_px: int = 15

    def __post_init__(self):
        """Validate parameters."""
        self.sensitivity = max(0.0, min(1.0, self.sensitivity))
        self.min_peak_distance = max(1, self.min_peak_distance)
        self.min_prominence = max(0.001, min(1.0, self.min_prominence))
        self.min_width_px = max(1, self.min_width_px)
        self.max_width_px = max(self.min_width_px + 1, self.max_width_px)
        self.match_tolerance_px = max(1, self.match_tolerance_px)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "sensitivity": self.sensitivity,
            "min_peak_distance": self.min_peak_distance,
            "min_prominence": self.min_prominence,
            "min_width_px": self.min_width_px,
            "max_width_px": self.max_width_px,
            "enable_shoulder_detection": self.enable_shoulder_detection,
            "enable_deconvolution": self.enable_deconvolution,
            "deconvolution_threshold_px": self.deconvolution_threshold_px,
            "match_tolerance_px": self.match_tolerance_px,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PeakDetectionParams:
        """Create from dictionary."""
        if not data:
            return cls()
        valid_fields = {
            "sensitivity",
            "min_peak_distance",
            "min_prominence",
            "min_width_px",
            "max_width_px",
            "enable_shoulder_detection",
            "enable_deconvolution",
            "deconvolution_threshold_px",
            "match_tolerance_px",
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class DetectedPeakWithMatch:
    """
    A detected peak from profile analysis with band matching information.

    Used to identify peaks in the electropherogram that may or may not
    have corresponding Band annotations.

    Attributes:
        y_position: Y position in image pixels (peak center).
        height: Peak height (intensity at peak).
        prominence: Peak prominence relative to surrounding baseline.
        width_px: Peak width in pixels (FWHM estimate).
        left_base: Left boundary of peak region.
        right_base: Right boundary of peak region.
        snr: Signal-to-noise ratio.
        area: Estimated peak area.
        sigma: Gaussian sigma (if fitted).
        is_shoulder: Whether this peak was detected as a shoulder.

        # Matching information
        is_orphan: True if no existing band matches this peak.
        matched_band_id: UUID of matched Band, or None.
        match_distance_px: Distance to matched band center.
    """

    y_position: int
    height: float = 0.0
    prominence: float = 0.0
    width_px: int = 10
    left_base: int = 0
    right_base: int = 0
    snr: float = 0.0
    area: float = 0.0
    sigma: float = 0.0
    is_shoulder: bool = False

    # Matching info
    is_orphan: bool = True
    matched_band_id: str | None = None
    match_distance_px: int | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "y_position": self.y_position,
            "height": round(self.height, 2),
            "prominence": round(self.prominence, 2),
            "width_px": self.width_px,
            "left_base": self.left_base,
            "right_base": self.right_base,
            "snr": round(self.snr, 2),
            "area": round(self.area, 2),
            "sigma": round(self.sigma, 2),
            "is_shoulder": self.is_shoulder,
            "is_orphan": self.is_orphan,
            "matched_band_id": self.matched_band_id,
            "match_distance_px": self.match_distance_px,
        }


@dataclass
class PeakDetectionResult:
    """
    Result of peak detection for a lane.

    Contains all detected peaks with matching information.
    """

    lane_id: int
    peaks: list[DetectedPeakWithMatch] = field(default_factory=list)
    total_peaks: int = 0
    orphan_count: int = 0
    matched_count: int = 0
    shoulder_count: int = 0
    success: bool = True
    error_message: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "lane_id": self.lane_id,
            "peaks": [p.to_dict() for p in self.peaks],
            "total_peaks": self.total_peaks,
            "orphan_count": self.orphan_count,
            "matched_count": self.matched_count,
            "shoulder_count": self.shoulder_count,
            "success": self.success,
            "error_message": self.error_message,
        }


@dataclass
class PeakIntegrationResult:
    """
    Result of peak integration for a single band.

    Stores Gaussian fit parameters, integration values, and quality metrics.

    Attributes:
        band_id: UUID of the Band model
        band_type: Band classification (POI, OTHER, MW_REFERENCE)
        position_y: Y position of band center in image
        estimated_mw_kda: Estimated molecular weight (if calibrated)

        # Gaussian fit parameters
        peak_center: Fitted peak center Y position
        amplitude: Gaussian amplitude (peak height)
        sigma: Gaussian width parameter
        fwhm: Full Width at Half Maximum

        # Integration results
        integrated_area: Total area under the curve
        background_area: Background contribution
        corrected_area: Background-corrected area
        raw_trapezoid_area: Area by trapezoidal integration (fallback)

        # Quality metrics
        fit_r_squared: Goodness of fit (0-1)
        snr: Signal-to-noise ratio
        fit_successful: Whether Gaussian fit succeeded

        # Relative quantification (filled by normalizer)
        relative_percent_lane: Percentage of lane total
        relative_percent_gel: Percentage of gel total
    """

    band_id: str
    band_type: str = "OTHER"
    position_y: int = 0
    estimated_mw_kda: float | None = None

    # Gaussian fit parameters
    peak_center: float = 0.0
    amplitude: float = 0.0
    sigma: float = 0.0
    fwhm: float = 0.0

    # Integration results
    integrated_area: float = 0.0
    background_area: float = 0.0
    corrected_area: float = 0.0
    raw_trapezoid_area: float = 0.0

    # Quality metrics
    fit_r_squared: float = 0.0
    snr: float = 0.0
    fit_successful: bool = False

    # Relative quantification
    relative_percent_lane: float | None = None
    relative_percent_gel: float | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "band_id": self.band_id,
            "band_type": self.band_type,
            "position_y": self.position_y,
            "estimated_mw_kda": round(self.estimated_mw_kda, 1) if self.estimated_mw_kda else None,
            "peak_center": round(self.peak_center, 2),
            "amplitude": round(self.amplitude, 2),
            "sigma": round(self.sigma, 2),
            "fwhm": round(self.fwhm, 2),
            "integrated_area": round(self.integrated_area, 2),
            "background_area": round(self.background_area, 2),
            "corrected_area": round(self.corrected_area, 2),
            "raw_trapezoid_area": round(self.raw_trapezoid_area, 2),
            "fit_r_squared": round(self.fit_r_squared, 4),
            "snr": round(self.snr, 2),
            "fit_successful": self.fit_successful,
            "relative_percent_lane": round(self.relative_percent_lane, 2)
            if self.relative_percent_lane is not None
            else None,
            "relative_percent_gel": round(self.relative_percent_gel, 2)
            if self.relative_percent_gel is not None
            else None,
        }

    @property
    def fit_quality(self) -> str:
        """Return quality indicator based on R-squared value."""
        if not self.fit_successful:
            return "failed"
        if self.fit_r_squared >= 0.99:
            return "excellent"
        elif self.fit_r_squared >= 0.95:
            return "good"
        elif self.fit_r_squared >= 0.90:
            return "acceptable"
        elif self.fit_r_squared >= 0.80:
            return "fair"
        else:
            return "poor"


@dataclass
class LaneProfileData:
    """
    Lane intensity profile data for chart visualization.

    Stores the processed intensity profile with MW axis conversion
    for rendering in the electropherogram/chromatogram view.

    Attributes:
        y_positions: Y positions in image pixels
        intensities: Processed (background-corrected) intensity values
        mw_values: Molecular weight values at each position (if calibrated)
        background: Background signal values
        raw_intensities: Raw (unprocessed) intensity values
    """

    y_positions: list[int] = field(default_factory=list)
    intensities: list[float] = field(default_factory=list)
    mw_values: list[float] = field(default_factory=list)
    background: list[float] = field(default_factory=list)
    raw_intensities: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "y_positions": self.y_positions,
            "intensities": [round(v, 2) for v in self.intensities],
            "mw_values": [round(v, 2) if v else None for v in self.mw_values],
            "background": [round(v, 2) for v in self.background],
            "raw_intensities": [round(v, 2) for v in self.raw_intensities],
            "point_count": len(self.y_positions),
        }


@dataclass
class LaneDensitometryResultData:
    """
    Complete densitometry result for a lane.

    Contains all band integration results plus summary statistics.

    Attributes:
        lane_id: Database ID of the Lane model
        lane_number: Lane number (1-indexed from left)
        lane_type: Lane type (SAMPLE, LADDER, etc.)

        # Band results
        peaks: List of PeakIntegrationResult for each band
        bands_processed: Number of bands processed
        bands_successful: Number of bands with successful fits

        # Aggregated metrics
        total_integrated_area: Sum of all corrected areas
        poi_integrated_area: Sum of POI band areas
        poi_percentage: Purity (POI / Total * 100)
        other_integrated_area: Sum of OTHER band areas

        # Profile data for visualization
        profile_data: LaneProfileData for chart rendering

        # Processing info
        success: Whether processing completed successfully
        error_message: Error message if failed
        processing_time_ms: Time taken for processing
    """

    lane_id: int
    lane_number: int
    lane_type: str = "SAMPLE"

    # Band results
    peaks: list[PeakIntegrationResult] = field(default_factory=list)
    bands_processed: int = 0
    bands_successful: int = 0

    # Aggregated metrics
    total_integrated_area: float = 0.0
    poi_integrated_area: float | None = None
    poi_percentage: float | None = None
    other_integrated_area: float | None = None
    mw_reference_area: float | None = None

    # Profile data
    profile_data: LaneProfileData | None = None

    # Processing info
    success: bool = True
    error_message: str = ""
    processing_time_ms: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "lane_id": self.lane_id,
            "lane_number": self.lane_number,
            "lane_type": self.lane_type,
            "peaks": [p.to_dict() for p in self.peaks],
            "bands_processed": self.bands_processed,
            "bands_successful": self.bands_successful,
            "total_integrated_area": round(self.total_integrated_area, 2),
            "poi_integrated_area": round(self.poi_integrated_area, 2) if self.poi_integrated_area else None,
            "poi_percentage": round(self.poi_percentage, 2) if self.poi_percentage else None,
            "other_integrated_area": round(self.other_integrated_area, 2) if self.other_integrated_area else None,
            "mw_reference_area": round(self.mw_reference_area, 2) if self.mw_reference_area else None,
            "profile_data": self.profile_data.to_dict() if self.profile_data else None,
            "success": self.success,
            "error_message": self.error_message,
            "processing_time_ms": round(self.processing_time_ms, 1),
        }


@dataclass
class DensitometryAnalysisResult:
    """
    Full densitometry analysis result for a GelAnalysis.

    Contains results for all lanes plus gel-level statistics.

    Attributes:
        analysis_id: UUID of the GelAnalysis
        lanes: List of LaneDensitometryResultData
        lanes_processed: Number of lanes processed
        lanes_successful: Number of lanes successfully processed
        total_bands: Total bands across all lanes

        # Gel-level aggregation
        gel_total_area: Sum of all band areas in gel
        average_poi_percentage: Average purity across sample lanes

        # Parameters used
        params_used: DensitometryParams applied

        # Processing info
        success: Overall success status
        error_message: Error message if failed
        processing_time_ms: Total processing time
    """

    analysis_id: str
    lanes: list[LaneDensitometryResultData] = field(default_factory=list)
    lanes_processed: int = 0
    lanes_successful: int = 0
    total_bands: int = 0

    # Gel-level aggregation
    gel_total_area: float = 0.0
    average_poi_percentage: float | None = None

    # Parameters used
    params_used: DensitometryParams | None = None

    # Processing info
    success: bool = True
    error_message: str = ""
    processing_time_ms: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to dictionary for API response."""
        return {
            "analysis_id": self.analysis_id,
            "lanes": [lane.to_dict() for lane in self.lanes],
            "lanes_processed": self.lanes_processed,
            "lanes_successful": self.lanes_successful,
            "total_bands": self.total_bands,
            "gel_total_area": round(self.gel_total_area, 2),
            "average_poi_percentage": round(self.average_poi_percentage, 2) if self.average_poi_percentage else None,
            "params_used": self.params_used.to_dict() if self.params_used else None,
            "success": self.success,
            "error_message": self.error_message,
            "processing_time_ms": round(self.processing_time_ms, 1),
        }
