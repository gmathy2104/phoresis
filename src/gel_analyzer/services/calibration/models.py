"""
Dataclasses for calibration service parameters and results.

These dataclasses are used for:
- Configuring calibration behavior (CalibrationParams)
- Representing band matches (BandMatch)
- Returning calibration results (CalibrationResult)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CalibrationParams:
    """
    Parameters for MW calibration.

    Attributes:
        method: Regression method to use (LOG_LINEAR, POLYNOMIAL_2, POLYNOMIAL_3)
        min_bands: Minimum number of bands required for valid calibration
        outlier_threshold: Number of standard deviations for outlier detection
        use_reference_bands_only: If True, only use bands marked as reference bands
    """

    method: str = "LOG_LINEAR"
    min_bands: int = 3
    outlier_threshold: float = 2.0
    use_reference_bands_only: bool = False

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "method": self.method,
            "min_bands": self.min_bands,
            "outlier_threshold": self.outlier_threshold,
            "use_reference_bands_only": self.use_reference_bands_only,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CalibrationParams:
        """Create from dictionary (API request)."""
        if not data:
            return cls()
        valid_fields = {"method", "min_bands", "outlier_threshold", "use_reference_bands_only"}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class BandMatch:
    """
    Represents a match between a detected band and a template band.

    Attributes:
        band_id: UUID of the detected Band model
        template_band_order: Order of the matched template band (1=highest MW)
        mw_kda: Known molecular weight from template (kDa)
        position_y: Y position of band in image pixels
        rf: Relative migration (0=well, 1=dye front)
        residual: Fitting residual (log10 scale) after regression
    """

    band_id: str
    template_band_order: int
    mw_kda: float
    position_y: int
    rf: float
    residual: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to dictionary.

        Exposes the residual both in log-space (matches `residual` from the
        regression) and in absolute MW terms — `predicted_mw_kda` and
        `residual_pct` — so the marker-table UI can highlight outliers
        without re-doing the math client-side.
        """
        # residual = log10(declared) - log10(predicted)  →  predicted = declared / 10**residual
        try:
            predicted_mw = self.mw_kda / (10**self.residual) if self.mw_kda > 0 else None
            residual_pct = (
                ((predicted_mw - self.mw_kda) / self.mw_kda) * 100.0
                if predicted_mw is not None and self.mw_kda > 0
                else None
            )
        except (ZeroDivisionError, OverflowError, ValueError):
            predicted_mw = None
            residual_pct = None

        return {
            "band_id": self.band_id,
            "template_band_order": self.template_band_order,
            "mw_kda": self.mw_kda,
            "position_y": self.position_y,
            "rf": round(self.rf, 4),
            "residual": round(self.residual, 6),
            "predicted_mw_kda": round(predicted_mw, 2) if predicted_mw is not None else None,
            "residual_pct": round(residual_pct, 1) if residual_pct is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BandMatch:
        """Create from dictionary."""
        return cls(
            band_id=data["band_id"],
            template_band_order=data["template_band_order"],
            mw_kda=data["mw_kda"],
            position_y=data["position_y"],
            rf=data["rf"],
            residual=data.get("residual", 0.0),
        )


@dataclass
class CalibrationResult:
    """
    Result of a calibration computation.

    Attributes:
        success: Whether calibration succeeded
        method: Regression method used
        coefficients: Regression coefficients
            - LOG_LINEAR: {slope, intercept}
            - POLYNOMIAL_*: {coeffs: [a, b, c, ...]}
        r_squared: Coefficient of determination (0-1)
        equation: Human-readable equation string
        band_matches: List of matched bands with their Rf and residuals
        outliers: Bands excluded as outliers
        error_message: Error message if success=False
        warnings: List of warning messages (non-blocking issues)
    """

    success: bool
    method: str = ""
    coefficients: dict = field(default_factory=dict)
    r_squared: float = 0.0
    equation: str = ""
    band_matches: list[BandMatch] = field(default_factory=list)
    outliers: list[BandMatch] = field(default_factory=list)
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "success": self.success,
            "method": self.method,
            "coefficients": self.coefficients,
            "r_squared": round(self.r_squared, 6) if self.r_squared is not None else None,
            "equation": self.equation,
            "band_matches": [m.to_dict() for m in self.band_matches],
            "outliers": [m.to_dict() for m in self.outliers],
            "matched_band_count": len(self.band_matches),
            "error_message": self.error_message,
            "warnings": self.warnings,
        }

    @property
    def r_squared_quality(self) -> str:
        """Return quality indicator based on R² value."""
        if self.r_squared >= 0.99:
            return "excellent"
        elif self.r_squared >= 0.95:
            return "good"
        elif self.r_squared >= 0.90:
            return "acceptable"
        else:
            return "poor"


# Multi-Ladder Calibration Dataclasses


class InterpolationMethodType:
    """Constants for interpolation methods."""

    SINGLE = "SINGLE"
    LINEAR = "LINEAR"
    EDGE = "EDGE"


@dataclass
class LadderCalibrationData:
    """
    Data container for a single ladder calibration used in interpolation.

    Stores the essential data needed to compute MW estimates from a
    specific ladder lane calibration.

    Attributes:
        calibration_id: UUID of the LadderCalibration model
        ladder_x_position: X center position of ladder lane
        method: Calibration method (LOG_LINEAR, POLYNOMIAL_2, etc.)
        coefficients: Regression coefficients
        r_squared: Coefficient of determination
        lane_id: ID of the ladder lane
        lane_top: Y position of lane top
        lane_bottom: Y position of lane bottom
        band_matches: List of matched bands with Rf and MW values (for chart display)
    """

    calibration_id: str
    ladder_x_position: int
    method: str
    coefficients: dict
    r_squared: float
    lane_id: int
    lane_top: int
    lane_bottom: int
    band_matches: list = field(default_factory=list)
    excluded_band_ids: list = field(default_factory=list)

    def estimate_mw(self, position_y: int) -> float | None:
        """
        Calculate MW from Y position using this calibration.

        Args:
            position_y: Y position of band in pixels

        Returns:
            Estimated MW in kDa, or None if calculation fails
        """
        import numpy as np

        if self.lane_bottom <= self.lane_top:
            return None

        # Calculate Rf
        rf = (position_y - self.lane_top) / (self.lane_bottom - self.lane_top)
        rf = max(0.0, min(1.0, rf))

        try:
            if self.method == "LOG_LINEAR":
                slope = self.coefficients.get("slope", 0)
                intercept = self.coefficients.get("intercept", 0)
                log_mw = slope * rf + intercept
                return 10**log_mw

            elif self.method.startswith("POLYNOMIAL_"):
                coeffs = self.coefficients.get("coeffs", [])
                if not coeffs:
                    return None
                log_mw = np.polyval(coeffs, rf)
                return 10**log_mw

        except (ValueError, OverflowError, ZeroDivisionError):
            return None

        return None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "calibration_id": self.calibration_id,
            "ladder_x_position": self.ladder_x_position,
            "method": self.method,
            "coefficients": self.coefficients,
            "r_squared": round(self.r_squared, 6),
            "lane_id": self.lane_id,
            "lane_top": self.lane_top,
            "lane_bottom": self.lane_bottom,
            "band_matches": self.band_matches,
            "excluded_band_ids": self.excluded_band_ids,
        }


@dataclass
class InterpolationWeight:
    """
    Weight for a calibration in MW interpolation.

    Attributes:
        calibration_id: UUID of the LadderCalibration
        weight: Weight factor (0-1) for this calibration
        ladder_x: X position of the ladder lane
    """

    calibration_id: str
    weight: float
    ladder_x: int

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "calibration_id": self.calibration_id,
            "weight": round(self.weight, 4),
            "ladder_x": self.ladder_x,
        }


@dataclass
class InterpolatedMWResult:
    """
    Result of position-aware MW estimation using multi-ladder interpolation.

    Attributes:
        estimated_mw_kda: Interpolated molecular weight estimate
        method: Interpolation method used (SINGLE, LINEAR, EDGE)
        interpolation_weights: List of (calibration_id, weight) used
        left_ladder_mw: MW estimate from left ladder (if interpolated)
        right_ladder_mw: MW estimate from right ladder (if interpolated)
        confidence: Confidence factor based on R² values and distance
    """

    estimated_mw_kda: float
    method: str
    interpolation_weights: list[InterpolationWeight] = field(default_factory=list)
    left_ladder_mw: float | None = None
    right_ladder_mw: float | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "estimated_mw_kda": round(self.estimated_mw_kda, 1) if self.estimated_mw_kda else None,
            "method": self.method,
            "interpolation_weights": [w.to_dict() for w in self.interpolation_weights],
            "left_ladder_mw": round(self.left_ladder_mw, 1) if self.left_ladder_mw else None,
            "right_ladder_mw": round(self.right_ladder_mw, 1) if self.right_ladder_mw else None,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class MultiLadderCalibrationResult:
    """
    Result of multi-ladder calibration for an analysis.

    Contains results from calibrating all ladder lanes with the same template.

    Attributes:
        success: Overall success (at least one ladder calibrated)
        template_id: UUID of the template used
        template_name: Name of the template
        calibrations: List of successful CalibrationResult per ladder
        errors: List of error messages for failed ladders
        ladder_count: Number of successfully calibrated ladders
        average_r_squared: Average R² across all calibrations
        warnings: List of warning messages (non-blocking issues)
    """

    success: bool
    template_id: str | None = None
    template_name: str | None = None
    calibrations: list[CalibrationResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    ladder_count: int = 0
    average_r_squared: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "success": self.success,
            "template_id": self.template_id,
            "template_name": self.template_name,
            "calibrations": [c.to_dict() for c in self.calibrations],
            "errors": self.errors,
            "ladder_count": self.ladder_count,
            "average_r_squared": round(self.average_r_squared, 6) if self.average_r_squared is not None else None,
            "warnings": self.warnings,
        }
