"""
Peak integration using Gaussian fitting.

Performs Gaussian curve fitting to band intensity profiles and computes
integrated areas for quantitative densitometry analysis.

Uses scipy.optimize.curve_fit for non-linear least squares fitting.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.integrate import trapezoid
from scipy.optimize import curve_fit

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import Band
    from gel_analyzer.services.band_detection.models import IntensityProfile

from .models import DensitometryParams, PeakIntegrationResult

logger = get_logger(__name__)


def gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
    """
    Gaussian function for curve fitting.

    Args:
        x: X values (Y positions in profile)
        amplitude: Peak amplitude (height)
        center: Peak center position
        sigma: Standard deviation (width parameter)

    Returns:
        Gaussian curve values
    """
    return amplitude * np.exp(-((x - center) ** 2) / (2 * sigma**2))


def gaussian_with_baseline(x: np.ndarray, amplitude: float, center: float, sigma: float, baseline: float) -> np.ndarray:
    """
    Gaussian function with constant baseline.

    Args:
        x: X values
        amplitude: Peak amplitude
        center: Peak center
        sigma: Standard deviation
        baseline: Constant baseline offset

    Returns:
        Gaussian + baseline values
    """
    return gaussian(x, amplitude, center, sigma) + baseline


class PeakIntegrator:
    """
    Integrate band peaks using Gaussian fitting.

    Fits Gaussian curves to intensity profile peaks corresponding to bands
    and computes integrated areas. Falls back to trapezoidal integration
    if Gaussian fitting fails.

    Usage:
        integrator = PeakIntegrator(params)
        result = integrator.integrate_band(band, profile)
    """

    def __init__(self, params: DensitometryParams):
        """
        Initialize integrator with parameters.

        Args:
            params: Densitometry parameters controlling fit behavior.
        """
        self.params = params
        # If profile is already background-corrected by ProfileProcessor,
        # we should NOT subtract background again during integration
        self.profile_already_corrected = getattr(params, "profile_already_corrected", True)

        if self.profile_already_corrected:
            logger.debug("PeakIntegrator: profile_already_corrected=True, skipping bg subtraction")
        else:
            logger.debug("PeakIntegrator: profile_already_corrected=False, will subtract bg")

    def integrate_band(
        self,
        band: Band,
        profile: IntensityProfile,
        background: np.ndarray | None = None,
    ) -> PeakIntegrationResult:
        """
        Integrate a single band peak.

        Extracts the region of the intensity profile corresponding to the band,
        fits a Gaussian curve, and computes the integrated area.

        Args:
            band: Band model instance with position and geometry.
            profile: Intensity profile for the lane containing the band.
            background: Optional pre-computed background array.

        Returns:
            PeakIntegrationResult with fit parameters and integrated area.
        """
        result = PeakIntegrationResult(
            band_id=str(band.id),
            band_type=band.band_type,
            position_y=band.position_y,
            estimated_mw_kda=band.estimated_mw_kda,
        )

        try:
            # Extract band region from profile
            y_positions = np.array(profile.y_positions)
            intensities = np.array(profile.processed_intensities)

            if len(y_positions) == 0 or len(intensities) == 0:
                logger.warning(f"Empty profile for band {band.id}")
                result.error_message = "Empty profile"
                return result

            # Find band region in profile
            band_y = band.position_y
            band_bbox = band.bbox

            if band_bbox:
                # Use bounding box for region
                band_top = band_bbox["y"]
                band_bottom = band_bbox["y"] + band_bbox["height"]
            else:
                # Estimate region from position and typical width
                band_top = band_y - 20
                band_bottom = band_y + 20

            # Get indices within band region
            mask = (y_positions >= band_top) & (y_positions <= band_bottom)
            region_y = y_positions[mask]
            region_intensity = intensities[mask]

            if len(region_y) < 5:
                logger.warning(f"Insufficient points for band {band.id}: {len(region_y)}")
                # Fall back to trapezoidal integration
                return self._trapezoid_fallback(result, region_y, region_intensity, background, mask)

            # Compute background for region
            if background is not None:
                region_background = background[mask]
                bg_area = float(trapezoid(region_background, region_y))
            else:
                region_background = np.zeros_like(region_intensity)
                bg_area = 0.0

            result.background_area = bg_area

            # Trapezoidal integration (always computed as fallback)
            raw_area = float(trapezoid(region_intensity, region_y))
            result.raw_trapezoid_area = raw_area

            if not self.params.gaussian_fit_enabled:
                # Skip Gaussian fitting, use trapezoid
                result.integrated_area = raw_area
                if self.profile_already_corrected:
                    # Profile already corrected - use raw area directly
                    result.corrected_area = raw_area
                else:
                    # Profile not corrected - subtract background
                    result.corrected_area = raw_area - bg_area
                result.fit_successful = False
                return result

            # Attempt Gaussian fit
            fit_result = self._fit_gaussian(region_y, region_intensity, band_y)

            if fit_result is not None:
                amplitude, center, sigma, r_squared = fit_result

                # Compute FWHM: FWHM = 2 * sqrt(2 * ln(2)) * sigma
                fwhm = 2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma

                # Integrated area of Gaussian: A = amplitude * sigma * sqrt(2*pi)
                gaussian_area = amplitude * sigma * math.sqrt(2.0 * math.pi)

                # Check fit quality
                if r_squared >= self.params.min_fit_r_squared:
                    result.peak_center = center
                    result.amplitude = amplitude
                    result.sigma = sigma
                    result.fwhm = fwhm
                    result.integrated_area = gaussian_area
                    if self.profile_already_corrected:
                        # Profile already corrected - use Gaussian area directly
                        result.corrected_area = gaussian_area
                    else:
                        # Profile not corrected - subtract background
                        result.corrected_area = gaussian_area - bg_area
                    result.fit_r_squared = r_squared
                    result.fit_successful = True

                    # Compute SNR
                    noise = self._estimate_noise(region_intensity)
                    result.snr = amplitude / noise if noise > 0 else 0.0

                    logger.debug(
                        f"Band {band.id}: Gaussian fit R²={r_squared:.4f}, area={gaussian_area:.1f}, fwhm={fwhm:.1f}px"
                    )
                else:
                    # Fit quality too low, use trapezoid
                    logger.debug(f"Band {band.id}: Gaussian fit R²={r_squared:.4f} below threshold, using trapezoid")
                    result.integrated_area = raw_area
                    if self.profile_already_corrected:
                        result.corrected_area = raw_area
                    else:
                        result.corrected_area = raw_area - bg_area
                    result.fit_r_squared = r_squared
                    result.fit_successful = False
            else:
                # Fitting failed, use trapezoid
                result.integrated_area = raw_area
                if self.profile_already_corrected:
                    result.corrected_area = raw_area
                else:
                    result.corrected_area = raw_area - bg_area
                result.fit_successful = False

            # Ensure corrected area is non-negative
            result.corrected_area = max(0.0, result.corrected_area)

        except Exception as e:
            logger.exception(f"Error integrating band {band.id}: {e}")
            result.fit_successful = False

        return result

    def _fit_gaussian(
        self,
        x: np.ndarray,
        y: np.ndarray,
        initial_center: float,
    ) -> tuple[float, float, float, float] | None:
        """
        Fit Gaussian curve to data.

        Args:
            x: X values (Y positions)
            y: Y values (intensities)
            initial_center: Initial guess for peak center

        Returns:
            Tuple of (amplitude, center, sigma, r_squared) or None if failed.
        """
        try:
            # Initial parameter guesses
            amplitude_guess = float(np.max(y) - np.min(y))
            center_guess = initial_center
            sigma_guess = (x[-1] - x[0]) / 4.0  # ~1/4 of region width

            # Fit with constant baseline
            p0 = [amplitude_guess, center_guess, sigma_guess, float(np.min(y))]
            bounds_with_baseline = (
                [0, x[0] - 10, 1, 0],
                [amplitude_guess * 3, x[-1] + 10, (x[-1] - x[0]) * 2, np.max(y)],
            )

            popt, pcov = curve_fit(
                gaussian_with_baseline,
                x,
                y,
                p0=p0,
                bounds=bounds_with_baseline,
                maxfev=1000,
            )

            amplitude, center, sigma, baseline = popt

            # Compute R-squared
            y_fitted = gaussian_with_baseline(x, *popt)
            ss_res = np.sum((y - y_fitted) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            # Validate fit
            if sigma < 1 or sigma > (x[-1] - x[0]):
                logger.debug("Gaussian fit sigma out of reasonable range")
                return None

            if amplitude < 0:
                logger.debug("Gaussian fit produced negative amplitude")
                return None

            return (amplitude, center, sigma, r_squared)

        except (RuntimeError, ValueError) as e:
            logger.debug(f"Gaussian fit failed: {e}")
            return None

    def _trapezoid_fallback(
        self,
        result: PeakIntegrationResult,
        region_y: np.ndarray,
        region_intensity: np.ndarray,
        background: np.ndarray | None,
        mask: np.ndarray,
    ) -> PeakIntegrationResult:
        """
        Fall back to trapezoidal integration when Gaussian fit is not possible.

        Args:
            result: PeakIntegrationResult to update
            region_y: Y positions in band region
            region_intensity: Intensities in band region
            background: Full background array
            mask: Boolean mask for band region

        Returns:
            Updated PeakIntegrationResult
        """
        if len(region_y) == 0:
            result.integrated_area = 0.0
            result.corrected_area = 0.0
            return result

        raw_area = float(trapezoid(region_intensity, region_y)) if len(region_y) > 1 else 0.0
        result.raw_trapezoid_area = raw_area
        result.integrated_area = raw_area

        if background is not None and len(background) > 0:
            region_bg = background[mask] if len(background) == len(mask) else np.zeros_like(region_intensity)
            bg_area = float(trapezoid(region_bg, region_y)) if len(region_y) > 1 else 0.0
            result.background_area = bg_area
            if self.profile_already_corrected:
                # Profile already corrected - use raw area directly
                result.corrected_area = raw_area
            else:
                # Profile not corrected - subtract background
                result.corrected_area = max(0.0, raw_area - bg_area)
        else:
            result.corrected_area = raw_area

        result.fit_successful = False
        return result

    def _estimate_noise(self, data: np.ndarray) -> float:
        """
        Estimate noise level using Median Absolute Deviation.

        Args:
            data: Signal data

        Returns:
            Estimated noise standard deviation
        """
        if len(data) < 3:
            return 1.0

        # First derivative to remove trends
        diff = np.diff(data)

        # MAD of differences
        mad = np.median(np.abs(diff - np.median(diff)))

        # Convert MAD to std estimate (for normal distribution)
        noise = 1.4826 * mad

        return max(noise, 1.0)  # Minimum noise of 1 to avoid division by zero

    def integrate_bands(
        self,
        bands: list[Band],
        profile: IntensityProfile,
        background: np.ndarray | None = None,
    ) -> list[PeakIntegrationResult]:
        """
        Integrate multiple bands from a lane.

        Args:
            bands: List of Band model instances
            profile: Intensity profile for the lane
            background: Optional pre-computed background array

        Returns:
            List of PeakIntegrationResult for each band
        """
        results = []
        for band in bands:
            result = self.integrate_band(band, profile, background)
            results.append(result)
        return results
