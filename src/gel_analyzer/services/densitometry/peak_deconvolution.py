"""
Peak deconvolution using multi-Gaussian fitting with lmfit.

Deconvolves overlapping peaks into individual Gaussian components
for accurate quantification of partially resolved bands.

Supports:
- Multi-Gaussian fitting (2-5 components)
- Skewed Gaussian (EMG) for asymmetric peaks
- Automatic component number estimation
- Quality metrics (R-squared, residuals)

Based on HPLC chromatography deconvolution methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

try:
    from lmfit import Parameters
    from lmfit.models import GaussianModel, SkewedGaussianModel

    LMFIT_AVAILABLE = True
except ImportError:
    LMFIT_AVAILABLE = False

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.services.band_detection.models import IntensityProfile

from .models import DetectedPeakWithMatch

logger = get_logger(__name__)


@dataclass
class GaussianComponent:
    """
    A single Gaussian component from deconvolution.

    Attributes:
        center: Peak center position (Y coordinate).
        amplitude: Peak amplitude (height).
        sigma: Gaussian width parameter.
        area: Integrated area under the Gaussian.
        fwhm: Full Width at Half Maximum.
    """

    center: float
    amplitude: float
    sigma: float
    area: float = 0.0
    fwhm: float = 0.0

    def __post_init__(self):
        """Calculate derived values."""
        # FWHM = 2 * sqrt(2 * ln(2)) * sigma ≈ 2.355 * sigma
        self.fwhm = 2.355 * self.sigma
        # Gaussian area = amplitude * sigma * sqrt(2 * pi)
        if self.area == 0.0:
            self.area = self.amplitude * self.sigma * np.sqrt(2 * np.pi)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "center": round(self.center, 2),
            "amplitude": round(self.amplitude, 2),
            "sigma": round(self.sigma, 2),
            "area": round(self.area, 2),
            "fwhm": round(self.fwhm, 2),
        }


@dataclass
class DeconvolutionResult:
    """
    Result of peak deconvolution.

    Attributes:
        success: Whether fitting succeeded.
        n_components: Number of Gaussian components fitted.
        components: List of GaussianComponent objects.
        r_squared: Goodness of fit (0-1).
        residual_std: Standard deviation of residuals.
        original_peak_y: Y position of the original wide peak.
        error_message: Error message if failed.
    """

    success: bool = False
    n_components: int = 0
    components: list[GaussianComponent] = field(default_factory=list)
    r_squared: float = 0.0
    residual_std: float = 0.0
    original_peak_y: int = 0
    error_message: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "n_components": self.n_components,
            "components": [c.to_dict() for c in self.components],
            "r_squared": round(self.r_squared, 4),
            "residual_std": round(self.residual_std, 2),
            "original_peak_y": self.original_peak_y,
            "error_message": self.error_message,
        }


class PeakDeconvolutionService:
    """
    Deconvolve overlapping peaks using multi-Gaussian fitting.

    Uses lmfit library for robust non-linear least squares fitting
    with parameter constraints.

    Usage:
        service = PeakDeconvolutionService()
        result = service.deconvolve_peak(profile, peak, n_components=2)
    """

    def __init__(self, max_iterations: int = 1000, min_r_squared: float = 0.85):
        """
        Initialize deconvolution service.

        Args:
            max_iterations: Maximum iterations for fitting.
            min_r_squared: Minimum R-squared to accept fit.
        """
        if not LMFIT_AVAILABLE:
            logger.warning("lmfit not available, deconvolution disabled")

        self.max_iterations = max_iterations
        self.min_r_squared = min_r_squared

    def deconvolve_peak(
        self,
        profile: IntensityProfile,
        peak: DetectedPeakWithMatch,
        n_components: int = 2,
        use_skewed: bool = False,
    ) -> DeconvolutionResult:
        """
        Deconvolve a wide peak into multiple Gaussian components.

        Args:
            profile: IntensityProfile containing the peak.
            peak: The wide peak to deconvolve.
            n_components: Number of Gaussian components (2-5).
            use_skewed: Use SkewedGaussianModel for asymmetric peaks.

        Returns:
            DeconvolutionResult with fitted components.
        """
        result = DeconvolutionResult(original_peak_y=peak.y_position)

        if not LMFIT_AVAILABLE:
            result.error_message = "lmfit not available"
            return result

        # Validate inputs
        n_components = max(2, min(5, n_components))

        try:
            # Extract region around peak
            y_positions = np.array(profile.y_positions)
            intensities = np.array(profile.processed_intensities)

            # Find region indices
            margin = int(peak.width_px * 1.5)
            left_y = peak.left_base - margin
            right_y = peak.right_base + margin

            mask = (y_positions >= left_y) & (y_positions <= right_y)
            region_y = y_positions[mask]
            region_intensity = intensities[mask]

            if len(region_y) < n_components * 4:
                result.error_message = f"Insufficient data points: {len(region_y)}"
                return result

            # Build composite model
            if use_skewed:
                fitted_result = self._fit_skewed_gaussians(region_y, region_intensity, n_components, peak)
            else:
                fitted_result = self._fit_gaussians(region_y, region_intensity, n_components, peak)

            return fitted_result

        except Exception as e:
            logger.exception(f"Deconvolution failed: {e}")
            result.error_message = str(e)
            return result

    def _fit_gaussians(
        self,
        x: np.ndarray,
        y: np.ndarray,
        n_components: int,
        peak: DetectedPeakWithMatch,
    ) -> DeconvolutionResult:
        """
        Fit multiple Gaussian components to data.

        Args:
            x: X values (Y positions).
            y: Y values (intensities).
            n_components: Number of components.
            peak: Original peak for initial guesses.

        Returns:
            DeconvolutionResult.
        """
        result = DeconvolutionResult(
            original_peak_y=peak.y_position,
            n_components=n_components,
        )

        # Build composite model
        model = None
        params = Parameters()

        x_range = float(x[-1] - x[0])
        y_max = float(np.max(y))
        y_min = float(np.min(y))

        for i in range(n_components):
            prefix = f"g{i}_"

            # Create Gaussian model
            g_model = GaussianModel(prefix=prefix)

            model = g_model if model is None else model + g_model

            # Initial guesses: distribute centers across the region
            center_guess = x[0] + (i + 0.5) * x_range / n_components
            amplitude_guess = (y_max - y_min) / n_components
            sigma_guess = x_range / (n_components * 4)

            # Add parameters with bounds
            params.add(f"{prefix}center", value=center_guess, min=x[0], max=x[-1])
            params.add(f"{prefix}amplitude", value=amplitude_guess, min=0, max=y_max * 2)
            params.add(f"{prefix}sigma", value=sigma_guess, min=1, max=x_range / 2)

        # Fit
        try:
            fit_result = model.fit(y, params, x=x, max_nfev=self.max_iterations)

            if not fit_result.success:
                result.error_message = "Fit did not converge"
                return result

            # Calculate R-squared
            ss_res = np.sum(fit_result.residual**2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            result.r_squared = r_squared
            result.residual_std = float(np.std(fit_result.residual))

            # Check fit quality
            if r_squared < self.min_r_squared:
                result.error_message = f"R² too low: {r_squared:.3f}"
                return result

            # Extract components
            for i in range(n_components):
                prefix = f"g{i}_"
                center = fit_result.params[f"{prefix}center"].value
                amplitude = fit_result.params[f"{prefix}amplitude"].value
                sigma = fit_result.params[f"{prefix}sigma"].value

                component = GaussianComponent(
                    center=center,
                    amplitude=amplitude,
                    sigma=sigma,
                )
                result.components.append(component)

            # Sort components by center position
            result.components.sort(key=lambda c: c.center)
            result.success = True

        except Exception as e:
            result.error_message = f"Fitting error: {e}"

        return result

    def _fit_skewed_gaussians(
        self,
        x: np.ndarray,
        y: np.ndarray,
        n_components: int,
        peak: DetectedPeakWithMatch,
    ) -> DeconvolutionResult:
        """
        Fit skewed Gaussian (EMG-like) components for asymmetric peaks.

        Args:
            x: X values.
            y: Y values.
            n_components: Number of components.
            peak: Original peak.

        Returns:
            DeconvolutionResult.
        """
        result = DeconvolutionResult(
            original_peak_y=peak.y_position,
            n_components=n_components,
        )

        # Build composite model with skewed Gaussians
        model = None
        params = Parameters()

        x_range = float(x[-1] - x[0])
        y_max = float(np.max(y))
        y_min = float(np.min(y))

        for i in range(n_components):
            prefix = f"sg{i}_"

            sg_model = SkewedGaussianModel(prefix=prefix)

            model = sg_model if model is None else model + sg_model

            center_guess = x[0] + (i + 0.5) * x_range / n_components
            amplitude_guess = (y_max - y_min) / n_components
            sigma_guess = x_range / (n_components * 4)

            params.add(f"{prefix}center", value=center_guess, min=x[0], max=x[-1])
            params.add(f"{prefix}amplitude", value=amplitude_guess, min=0, max=y_max * 2)
            params.add(f"{prefix}sigma", value=sigma_guess, min=1, max=x_range / 2)
            params.add(f"{prefix}gamma", value=0, min=-2, max=2)  # Skewness

        try:
            fit_result = model.fit(y, params, x=x, max_nfev=self.max_iterations)

            if not fit_result.success:
                result.error_message = "Fit did not converge"
                return result

            ss_res = np.sum(fit_result.residual**2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            result.r_squared = r_squared
            result.residual_std = float(np.std(fit_result.residual))

            if r_squared < self.min_r_squared:
                result.error_message = f"R² too low: {r_squared:.3f}"
                return result

            for i in range(n_components):
                prefix = f"sg{i}_"
                center = fit_result.params[f"{prefix}center"].value
                amplitude = fit_result.params[f"{prefix}amplitude"].value
                sigma = fit_result.params[f"{prefix}sigma"].value

                component = GaussianComponent(
                    center=center,
                    amplitude=amplitude,
                    sigma=sigma,
                )
                result.components.append(component)

            result.components.sort(key=lambda c: c.center)
            result.success = True

        except Exception as e:
            result.error_message = f"Fitting error: {e}"

        return result

    def estimate_component_count(
        self,
        profile: IntensityProfile,
        peak: DetectedPeakWithMatch,
    ) -> int:
        """
        Estimate the number of components in a wide peak.

        Uses second derivative zero-crossings within the peak region.

        Args:
            profile: IntensityProfile.
            peak: The peak to analyze.

        Returns:
            Estimated number of components (1-5).
        """
        try:
            y_positions = np.array(profile.y_positions)
            intensities = np.array(profile.processed_intensities)

            # Extract peak region
            mask = (y_positions >= peak.left_base) & (y_positions <= peak.right_base)
            region_intensity = intensities[mask]

            if len(region_intensity) < 10:
                return 1

            # Second derivative
            second_deriv = np.gradient(np.gradient(region_intensity))

            # Count sign changes (inflection points)
            sign_changes = np.sum(np.abs(np.diff(np.sign(second_deriv))) > 0)

            # Each peak contributes ~2 inflection points, so n_peaks ≈ sign_changes / 2
            estimated = max(1, min(5, sign_changes // 2))

            return estimated

        except Exception:
            return 2  # Default to 2 components

    def deconvolve_wide_peaks(
        self,
        profile: IntensityProfile,
        peaks: list[DetectedPeakWithMatch],
        width_threshold: int = 40,
    ) -> list[DetectedPeakWithMatch]:
        """
        Deconvolve all peaks wider than threshold and return expanded list.

        Args:
            profile: IntensityProfile.
            peaks: List of detected peaks.
            width_threshold: Only deconvolve peaks wider than this.

        Returns:
            Expanded list with deconvolved components replacing wide peaks.
        """
        if not LMFIT_AVAILABLE:
            logger.warning("lmfit not available, skipping deconvolution")
            return peaks

        result_peaks = []

        for peak in peaks:
            if peak.width_px <= width_threshold:
                # Keep narrow peaks as-is
                result_peaks.append(peak)
                continue

            # Estimate component count
            n_components = self.estimate_component_count(profile, peak)

            if n_components <= 1:
                result_peaks.append(peak)
                continue

            # Attempt deconvolution
            deconv_result = self.deconvolve_peak(profile, peak, n_components=n_components)

            if deconv_result.success and len(deconv_result.components) > 1:
                # Create new peaks from components
                for comp in deconv_result.components:
                    new_peak = DetectedPeakWithMatch(
                        y_position=int(comp.center),
                        height=comp.amplitude,
                        prominence=comp.amplitude * 0.6,  # Approximate
                        width_px=int(comp.fwhm),
                        left_base=int(comp.center - comp.sigma * 2),
                        right_base=int(comp.center + comp.sigma * 2),
                        area=comp.area,
                        sigma=comp.sigma,
                        is_shoulder=False,
                        is_orphan=True,
                    )
                    result_peaks.append(new_peak)

                logger.debug(f"Deconvolved peak at Y={peak.y_position} into {len(deconv_result.components)} components")
            else:
                # Keep original peak if deconvolution failed
                result_peaks.append(peak)

        return result_peaks
