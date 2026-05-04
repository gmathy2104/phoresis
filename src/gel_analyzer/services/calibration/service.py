"""
CalibrationService - Orchestrates MW calibration from ladder lanes.

The service:
1. Matches detected bands to template bands by position order
2. Computes regression (log-linear or polynomial)
3. Calculates R² and residuals
4. Can apply calibration to estimate MW for all bands
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.stats import linregress

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import Band, GelAnalysis, LadderCalibration, LadderTemplate, Lane

from .models import BandMatch, CalibrationParams, CalibrationResult

logger = get_logger(__name__)


class CalibrationService:
    """
    Orchestrates MW calibration from ladder lanes.

    The calibration process:
    1. Match detected bands in ladder lane to template bands by position order
    2. Calculate Rf (relative migration) for each band
    3. Fit regression model: log10(MW) = f(Rf)
    4. Calculate R² and residuals
    5. Optionally detect and exclude outliers

    Usage:
        service = CalibrationService(params)

        # Match bands to template (preview)
        matches = service.match_bands_to_template(lane, template)

        # Compute calibration
        result = service.calibrate(lane, template, matches)

        # Apply to all bands in analysis
        service.apply_calibration_to_bands(analysis, calibration)
    """

    def __init__(self, params: CalibrationParams | None = None):
        """
        Initialize service with calibration parameters.

        Args:
            params: Calibration parameters. If None, uses defaults.
        """
        self.params = params or CalibrationParams()

    def get_bands_with_assigned_mw(
        self,
        lane: Lane,
    ) -> tuple[list[BandMatch], list[str]]:
        """
        Get bands that have MW values already assigned in the Band Editor.

        This method prioritizes user annotations over automatic matching.
        Only bands with estimated_mw_kda set will be used for calibration.

        Args:
            lane: Lane model instance (should be LADDER type)

        Returns:
            Tuple of (list of BandMatch objects, list of warning messages)
        """
        warnings = []

        # Get bands with MW assigned, sorted by position_y (top to bottom)
        bands_with_mw = list(
            lane.bands.filter(estimated_mw_kda__isnull=False).exclude(estimated_mw_kda=0).order_by("position_y")
        )

        if not bands_with_mw:
            logger.warning(f"No bands with MW assigned in lane {lane.lane_number}")
            return [], ["No bands have MW values assigned. Use the Band Editor to assign MW values."]

        # Calculate lane bounds for Rf calculation
        lane_top = lane.y
        lane_bottom = lane.y + lane.height

        # Build matches and validate physical order
        matches = []
        previous_mw = None
        order_violations = []

        for i, band in enumerate(bands_with_mw):
            rf = self._calculate_rf(band.position_y, lane_top, lane_bottom)
            mw = float(band.estimated_mw_kda)

            # Check physical order: higher position_y (lower in gel) should have lower MW
            if previous_mw is not None and mw >= previous_mw:
                order_violations.append(
                    f"Band at Y={band.position_y} ({mw} kDa) should have lower MW than previous ({previous_mw} kDa)"
                )

            matches.append(
                BandMatch(
                    band_id=str(band.id),
                    template_band_order=i + 1,  # Use position order as template order
                    mw_kda=mw,
                    position_y=band.position_y,
                    rf=rf,
                )
            )

            previous_mw = mw

        if order_violations:
            warnings.append(
                f"MW order violations detected: {len(order_violations)} band(s) have incorrect MW order. "
                "Check band assignments in the Band Editor."
            )
            for v in order_violations[:3]:  # Limit to first 3 violations
                logger.warning(f"Order violation in lane {lane.lane_number}: {v}")

        logger.info(f"Found {len(matches)} bands with MW assigned in lane {lane.lane_number}")

        return matches, warnings

    def match_bands_to_template(
        self,
        lane: Lane,
        template: LadderTemplate,
    ) -> list[BandMatch]:
        """
        Match detected bands in lane to template bands.

        DEPRECATED: This method uses automatic position-based matching.
        Prefer using get_bands_with_assigned_mw() which uses MW values
        from the Band Editor.

        This method is kept for backward compatibility but will now
        first try to use bands with existing MW assignments.

        Args:
            lane: Lane model instance (should be LADDER type)
            template: LadderTemplate with band definitions

        Returns:
            List of BandMatch objects
        """
        # First, try to use bands with existing MW assignments
        matches, warnings = self.get_bands_with_assigned_mw(lane)

        if matches:
            logger.info(f"Using {len(matches)} bands with existing MW assignments (ignoring template for matching)")
            return matches

        # Fallback to template-based matching only if no MW assigned
        logger.info("No bands with MW assigned, falling back to template-based matching")

        # Get detected bands sorted by position_y (top to bottom)
        # De-duplicate bands at same position (prefer MANUAL over CV2)
        all_bands = list(lane.bands.order_by("position_y"))
        detected_bands = self._deduplicate_bands_by_position(all_bands)

        # Get template bands sorted by band_order (1=highest MW)
        template_bands = list(template.bands.order_by("band_order"))

        if not detected_bands:
            logger.warning(f"No bands detected in lane {lane.lane_number}")
            return []

        if not template_bands:
            logger.warning(f"No bands defined in template {template.name}")
            return []

        n_detected = len(detected_bands)
        n_template = len(template_bands)

        # Calculate lane bounds for Rf calculation
        lane_top = lane.y
        lane_bottom = lane.y + lane.height

        # Calculate Rf for all detected bands
        detected_with_rf = []
        for band in detected_bands:
            rf = self._calculate_rf(band.position_y, lane_top, lane_bottom)
            detected_with_rf.append((band, rf))

        # CASE 1: Same number of bands - direct mapping
        if n_detected == n_template:
            logger.info(f"Perfect match: {n_detected} detected = {n_template} template bands")
            matches = []
            for (band, rf), template_band in zip(detected_with_rf, template_bands, strict=False):
                matches.append(
                    BandMatch(
                        band_id=str(band.id),
                        template_band_order=template_band.band_order,
                        mw_kda=template_band.mw_kda,
                        position_y=band.position_y,
                        rf=rf,
                    )
                )
            return matches

        # CASE 2: More detected than template - identify outliers
        if n_detected > n_template:
            logger.info(f"More bands detected ({n_detected}) than template ({n_template}), identifying outliers...")
            return self._match_with_outlier_detection(detected_with_rf, template_bands, lane_top, lane_bottom)

        # CASE 3: Fewer detected than template - some bands missing
        logger.info(
            f"Fewer bands detected ({n_detected}) than template ({n_template}), some template bands won't match"
        )
        return self._match_with_missing_bands(detected_with_rf, template_bands, lane_top, lane_bottom)

    def _match_with_outlier_detection(
        self,
        detected_with_rf: list[tuple],
        template_bands: list,
        lane_top: int,
        lane_bottom: int,
    ) -> list[BandMatch]:
        """
        Match when there are more detected bands than template bands.

        Uses a hybrid approach combining:
        1. Hungarian algorithm for optimal assignment based on expected Rf positions
        2. Band confidence weighting
        3. RANSAC-style verification using calibration fit quality

        This approach is inspired by star pattern recognition and chromatography
        peak alignment algorithms which face similar outlier challenges.
        """
        from scipy.optimize import linear_sum_assignment

        n_detected = len(detected_with_rf)
        n_template = len(template_bands)

        # Step 1: Calculate expected Rf for each template band
        # Assuming log-linear relationship: log10(MW) = slope * Rf + intercept
        # We estimate expected Rf using the actual detected band positions
        template_mws = np.array([tb.mw_kda for tb in template_bands])
        log_mws = np.log10(template_mws)

        # Get actual Rf range from detected bands
        detected_rfs = np.array([rf for _, rf in detected_with_rf])
        rf_min = detected_rfs.min()
        rf_max = detected_rfs.max()

        # Map log MW to expected Rf (log MW is inversely related to Rf)
        log_mw_max = log_mws.max()
        log_mw_min = log_mws.min()
        log_range = log_mw_max - log_mw_min if log_mw_max != log_mw_min else 1.0

        expected_rfs = []
        for log_mw in log_mws:
            # Normalize: highest MW (max log) -> lowest Rf, lowest MW -> highest Rf
            normalized = (log_mw_max - log_mw) / log_range
            expected_rf = rf_min + normalized * (rf_max - rf_min)
            expected_rfs.append(expected_rf)
        expected_rfs = np.array(expected_rfs)

        # Step 2: Build cost matrix for Hungarian algorithm
        # Cost = position error weighted by inverse confidence
        # Lower cost = better match
        cost_matrix = np.zeros((n_detected, n_template))

        for i, (band, detected_rf) in enumerate(detected_with_rf):
            # Get band confidence (default 0.5 if not set)
            confidence = getattr(band, "confidence", 0.5) or 0.5
            confidence = max(0.1, min(1.0, confidence))  # Clamp to [0.1, 1.0]

            for j, expected_rf in enumerate(expected_rfs):
                # Position error (normalized by RF range)
                rf_range = rf_max - rf_min if rf_max != rf_min else 1.0
                position_error = abs(detected_rf - expected_rf) / rf_range

                # Cost: position error weighted by inverse confidence
                # High confidence bands get lower cost for same position error
                cost = position_error / confidence

                cost_matrix[i, j] = cost

        # Step 3: Run Hungarian algorithm
        # Since we have more rows (detected) than columns (template),
        # only n_template bands will be assigned
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        # Step 4: Build initial matches from assignment
        initial_matches = []
        for det_idx, templ_idx in zip(row_ind, col_ind, strict=False):
            band, rf = detected_with_rf[det_idx]
            template_band = template_bands[templ_idx]
            initial_matches.append(
                {
                    "det_idx": det_idx,
                    "templ_idx": templ_idx,
                    "band": band,
                    "rf": rf,
                    "template_band": template_band,
                    "cost": cost_matrix[det_idx, templ_idx],
                }
            )

        # Sort by template order
        initial_matches.sort(key=lambda m: m["templ_idx"])

        # Step 5: RANSAC-style verification - fit calibration and check residuals
        # Compute residuals for each match
        rf_values = np.array([m["rf"] for m in initial_matches])
        log_mw_values = np.array([np.log10(m["template_band"].mw_kda) for m in initial_matches])

        # Fit log-linear regression
        from scipy.stats import linregress

        fit = linregress(rf_values, log_mw_values)
        predicted = fit.slope * rf_values + fit.intercept
        residuals = np.abs(log_mw_values - predicted)

        # Calculate residual threshold (2 std deviations)
        residual_std = np.std(residuals)
        residual_threshold = 2.0 * residual_std

        # Mark high-residual matches for potential replacement
        for i, m in enumerate(initial_matches):
            m["residual"] = residuals[i]
            m["is_outlier"] = residuals[i] > residual_threshold

        # Step 6: Try to improve matches with high residuals
        # For each outlier, see if there's a better band nearby
        unassigned_indices = set(range(n_detected)) - {m["det_idx"] for m in initial_matches}

        for match in initial_matches:
            if not match["is_outlier"] or not unassigned_indices:
                continue

            expected_rf = expected_rfs[match["templ_idx"]]
            current_det_idx = match["det_idx"]
            current_rf = match["rf"]

            # Look for a better candidate among unassigned bands
            best_replacement = None
            best_error = abs(current_rf - expected_rf)

            for alt_idx in unassigned_indices:
                alt_band, alt_rf = detected_with_rf[alt_idx]
                alt_error = abs(alt_rf - expected_rf)

                # Consider confidence in the decision
                alt_conf = getattr(alt_band, "confidence", 0.5) or 0.5
                current_conf = getattr(match["band"], "confidence", 0.5) or 0.5

                # Replace if significantly better position OR similar position but higher confidence
                if (
                    alt_error < best_error * 0.8 or alt_error < best_error and alt_conf > current_conf
                ):  # Significantly closer
                    best_replacement = alt_idx
                    best_error = alt_error

            if best_replacement is not None:
                # Swap the bands
                new_band, new_rf = detected_with_rf[best_replacement]
                unassigned_indices.remove(best_replacement)
                unassigned_indices.add(current_det_idx)

                logger.debug(
                    f"Replacing outlier Y={match['band'].position_y} with Y={new_band.position_y} "
                    f"for {match['template_band'].mw_kda} kDa"
                )

                match["det_idx"] = best_replacement
                match["band"] = new_band
                match["rf"] = new_rf
                match["is_outlier"] = False

        # Step 7: Build final BandMatch objects
        matches = []
        for m in initial_matches:
            matches.append(
                BandMatch(
                    band_id=str(m["band"].id),
                    template_band_order=m["template_band"].band_order,
                    mw_kda=m["template_band"].mw_kda,
                    position_y=m["band"].position_y,
                    rf=m["rf"],
                )
            )

        # Log results
        outlier_count = n_detected - n_template
        assigned_indices = {m["det_idx"] for m in initial_matches}
        skipped_positions = [detected_with_rf[i][0].position_y for i in range(n_detected) if i not in assigned_indices]

        logger.info(
            f"Hungarian+RANSAC matching: {len(matches)}/{n_template} template bands matched, "
            f"skipped {outlier_count} outlier(s) at Y={skipped_positions}"
        )

        return matches

    def _match_with_missing_bands(
        self,
        detected_with_rf: list[tuple],
        template_bands: list,
        lane_top: int,
        lane_bottom: int,
    ) -> list[BandMatch]:
        """
        Match when there are fewer detected bands than template bands.

        Uses Rf distribution to estimate which template bands are present.
        """
        n_template = len(template_bands)

        # Calculate expected Rf distribution for template
        template_mws = [tb.mw_kda for tb in template_bands]
        log_mws = np.array([np.log10(mw) for mw in template_mws])

        # Normalize log MW to Rf scale (assuming log-linear relationship)
        log_mw_max = log_mws[0]
        log_mw_min = log_mws[-1]
        log_mw_range = log_mw_max - log_mw_min

        # Get actual Rf range
        actual_rf_min = detected_with_rf[0][1]
        actual_rf_max = detected_with_rf[-1][1]
        actual_rf_range = actual_rf_max - actual_rf_min

        # For each detected band, find closest template band
        matches = []
        used_template_indices = set()

        for band, detected_rf in detected_with_rf:
            best_template_idx = None
            best_diff = float("inf")

            for j, _tb in enumerate(template_bands):
                if j in used_template_indices:
                    continue

                # Expected Rf for this template band
                expected_rel = (log_mw_max - log_mws[j]) / log_mw_range
                expected_rf = actual_rf_min + expected_rel * actual_rf_range

                diff = abs(detected_rf - expected_rf)
                if diff < best_diff:
                    best_diff = diff
                    best_template_idx = j

            if best_template_idx is not None:
                used_template_indices.add(best_template_idx)
                template_band = template_bands[best_template_idx]

                matches.append(
                    BandMatch(
                        band_id=str(band.id),
                        template_band_order=template_band.band_order,
                        mw_kda=template_band.mw_kda,
                        position_y=band.position_y,
                        rf=detected_rf,
                    )
                )
                logger.debug(f"Matched {template_band.mw_kda} kDa: Y={band.position_y}, Rf={detected_rf:.3f}")

        # Sort matches by template order for consistency
        matches.sort(key=lambda m: m.template_band_order)

        logger.info(f"Matched {len(matches)}/{n_template} template bands ({n_template - len(matches)} missing)")
        return matches

    def _deduplicate_bands_by_position(
        self,
        bands: list[Band],
        position_tolerance: int = 5,
    ) -> list[Band]:
        """
        De-duplicate bands that are at the same position.

        When both MANUAL and CV2 bands exist at similar positions,
        prefer MANUAL (human-verified) over CV2 (auto-detected).

        Args:
            bands: List of Band objects sorted by position_y
            position_tolerance: Max Y difference to consider as same position

        Returns:
            De-duplicated list of bands
        """
        if not bands:
            return []

        # Priority order: MANUAL > YOLO > AUTO (human verification > ML > derivative)
        source_priority = {"MANUAL": 0, "YOLO": 1, "CV2": 2}  # DB value is 'CV2' for AUTO

        result = []
        i = 0

        while i < len(bands):
            current = bands[i]
            group = [current]

            # Collect all bands within tolerance of current position
            j = i + 1
            while j < len(bands) and abs(bands[j].position_y - current.position_y) <= position_tolerance:
                group.append(bands[j])
                j += 1

            # Pick the best band from the group (by source priority)
            best = min(group, key=lambda b: source_priority.get(b.detection_source, 99))
            result.append(best)

            # Move past the group
            i = j

        if len(result) < len(bands):
            logger.debug(
                f"De-duplicated bands: {len(bands)} -> {len(result)} (removed {len(bands) - len(result)} duplicates)"
            )

        return result

    def calibrate(
        self,
        lane: Lane,
        template: LadderTemplate,
        matches: list[BandMatch] | None = None,
        warnings: list[str] | None = None,
    ) -> CalibrationResult:
        """
        Compute calibration curve from band matches.

        Args:
            lane: Lane model instance
            template: LadderTemplate used for calibration
            matches: Pre-computed band matches. If None, will compute.
            warnings: Pre-collected warnings to include in result.

        Returns:
            CalibrationResult with coefficients and statistics
        """
        collected_warnings = list(warnings) if warnings else []

        # Get matches if not provided - use bands with existing MW assignments
        if matches is None:
            matches, match_warnings = self.get_bands_with_assigned_mw(lane)
            collected_warnings.extend(match_warnings)

            # If no bands with MW, fall back to template matching (with warning)
            if not matches:
                logger.info(f"Falling back to template-based matching for lane {lane.lane_number}")
                matches = self.match_bands_to_template(lane, template)
                if matches:
                    collected_warnings.append(
                        "Used automatic template matching (no MW values assigned in Band Editor)."
                    )

        # Validate minimum bands
        if len(matches) < self.params.min_bands:
            return CalibrationResult(
                success=False,
                error_message=f"Need at least {self.params.min_bands} bands, got {len(matches)}",
                warnings=collected_warnings,
            )

        # Extract data arrays
        rf_values = np.array([m.rf for m in matches])
        mw_values = np.array([m.mw_kda for m in matches])
        log_mw_values = np.log10(mw_values)

        # Fit based on method
        if self.params.method == "LOG_LINEAR":
            result = self._fit_log_linear(rf_values, log_mw_values, matches)
        elif self.params.method == "POLYNOMIAL_2":
            result = self._fit_polynomial(rf_values, log_mw_values, matches, degree=2)
        elif self.params.method == "POLYNOMIAL_3":
            result = self._fit_polynomial(rf_values, log_mw_values, matches, degree=3)
        else:
            return CalibrationResult(
                success=False,
                error_message=f"Unknown calibration method: {self.params.method}",
                warnings=collected_warnings,
            )

        # Add collected warnings to result
        result.warnings = collected_warnings

        logger.info(f"Calibration complete: method={result.method}, R²={result.r_squared:.4f}, bands={len(matches)}")

        return result

    def _fit_log_linear(
        self,
        rf: np.ndarray,
        log_mw: np.ndarray,
        matches: list[BandMatch],
    ) -> CalibrationResult:
        """
        Fit log-linear regression: log10(MW) = slope * Rf + intercept

        This is the standard model for SDS-PAGE MW calibration.

        Args:
            rf: Array of Rf values
            log_mw: Array of log10(MW) values
            matches: List of band matches (will be updated with residuals)

        Returns:
            CalibrationResult
        """
        try:
            result = linregress(rf, log_mw)

            # Calculate residuals and update matches
            predicted = result.slope * rf + result.intercept
            residuals = log_mw - predicted

            for i, m in enumerate(matches):
                m.residual = float(residuals[i])

            # Build equation string
            slope_sign = "+" if result.intercept >= 0 else ""
            equation = f"log10(MW) = {result.slope:.4f} * Rf {slope_sign}{result.intercept:.4f}"

            return CalibrationResult(
                success=True,
                method="LOG_LINEAR",
                coefficients={
                    "slope": float(result.slope),
                    "intercept": float(result.intercept),
                },
                r_squared=float(result.rvalue**2),
                equation=equation,
                band_matches=matches,
            )

        except Exception as e:
            logger.error(f"Log-linear fit failed: {e}")
            return CalibrationResult(
                success=False,
                error_message=f"Regression failed: {str(e)}",
            )

    def _fit_polynomial(
        self,
        rf: np.ndarray,
        log_mw: np.ndarray,
        matches: list[BandMatch],
        degree: int,
    ) -> CalibrationResult:
        """
        Fit polynomial regression: log10(MW) = a*Rf^n + b*Rf^(n-1) + ... + c

        Higher-order polynomials can provide better fit for non-linear MW-Rf
        relationships, but risk overfitting.

        Args:
            rf: Array of Rf values
            log_mw: Array of log10(MW) values
            matches: List of band matches
            degree: Polynomial degree (2 or 3)

        Returns:
            CalibrationResult
        """
        try:
            # Fit polynomial
            coeffs = np.polyfit(rf, log_mw, degree)
            predicted = np.polyval(coeffs, rf)

            # Calculate R²
            ss_res = np.sum((log_mw - predicted) ** 2)
            ss_tot = np.sum((log_mw - np.mean(log_mw)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            # Calculate residuals
            residuals = log_mw - predicted
            for i, m in enumerate(matches):
                m.residual = float(residuals[i])

            # Build equation string
            equation = self._format_polynomial_equation(coeffs)

            return CalibrationResult(
                success=True,
                method=f"POLYNOMIAL_{degree}",
                coefficients={"coeffs": coeffs.tolist()},
                r_squared=float(r_squared),
                equation=equation,
                band_matches=matches,
            )

        except Exception as e:
            logger.error(f"Polynomial fit (degree={degree}) failed: {e}")
            return CalibrationResult(
                success=False,
                error_message=f"Polynomial regression failed: {str(e)}",
            )

    def _format_polynomial_equation(self, coeffs: np.ndarray) -> str:
        """Format polynomial coefficients as equation string."""
        terms = []
        degree = len(coeffs) - 1

        for i, c in enumerate(coeffs):
            power = degree - i
            c_str = f"{c:.4f}"

            if power == 0:
                terms.append(c_str)
            elif power == 1:
                terms.append(f"{c_str}*Rf")
            else:
                terms.append(f"{c_str}*Rf^{power}")

        return f"log10(MW) = {' + '.join(terms)}"

    def _calculate_rf(
        self,
        position_y: int,
        lane_top: int,
        lane_bottom: int,
    ) -> float:
        """
        Calculate relative migration (Rf) from Y position.

        Rf = 0 at the well (lane_top)
        Rf = 1 at the dye front (lane_bottom)

        Args:
            position_y: Y position of band in pixels
            lane_top: Y position of lane top (well)
            lane_bottom: Y position of lane bottom (dye front)

        Returns:
            Rf value (0-1)
        """
        if lane_bottom <= lane_top:
            return 0.0

        rf = (position_y - lane_top) / (lane_bottom - lane_top)
        return max(0.0, min(1.0, rf))

    def apply_calibration_to_bands(
        self,
        analysis: GelAnalysis,
        calibration: LadderCalibration,
    ) -> int:
        """
        Apply calibration to estimate MW for all bands in analysis.

        Updates the estimated_mw_kda field for all bands in non-ladder lanes.

        Args:
            analysis: GelAnalysis model instance
            calibration: LadderCalibration with computed coefficients

        Returns:
            Number of bands updated
        """
        updated = 0

        for lane in analysis.lanes.exclude(lane_type="LADDER"):
            lane_top = lane.y
            lane_bottom = lane.y + lane.height

            for band in lane.bands.all():
                mw = calibration.estimate_mw(
                    band.position_y,
                    lane_top,
                    lane_bottom,
                )
                if mw is not None:
                    band.estimated_mw_kda = mw
                    band.mw_estimation_method = calibration.method
                    band.save(update_fields=["estimated_mw_kda", "mw_estimation_method"])
                    updated += 1

        logger.info(f"Applied calibration to {updated} bands in analysis {analysis.pk}")

        return updated

    def estimate_mw_from_result(
        self,
        result: CalibrationResult,
        position_y: int,
        lane_top: int,
        lane_bottom: int,
    ) -> float | None:
        """
        Estimate MW from a CalibrationResult (without saved LadderCalibration).

        Useful for preview mode before saving calibration.

        Args:
            result: CalibrationResult with coefficients
            position_y: Y position of band
            lane_top: Y position of lane top
            lane_bottom: Y position of lane bottom

        Returns:
            Estimated MW in kDa, or None if calculation fails
        """
        if not result.success:
            return None

        rf = self._calculate_rf(position_y, lane_top, lane_bottom)

        try:
            if result.method == "LOG_LINEAR":
                slope = result.coefficients.get("slope", 0)
                intercept = result.coefficients.get("intercept", 0)
                log_mw = slope * rf + intercept
                return 10**log_mw

            elif result.method.startswith("POLYNOMIAL_"):
                coeffs = result.coefficients.get("coeffs", [])
                if not coeffs:
                    return None
                log_mw = np.polyval(coeffs, rf)
                return 10**log_mw

        except (ValueError, OverflowError):
            return None

        return None
