"""
MultiLadderCalibrationService - Position-aware MW estimation with interpolation.

This service handles gel smile correction by:
1. Calibrating multiple ladder lanes with the same template
2. Interpolating MW estimates based on sample X position
3. Using the closest ladder(s) for samples at the edges

Inspired by Phoretix 1D's iso-molecular weight line approach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    from gel_analyzer.models import (
        GelAnalysis,
        LadderTemplate,
    )

from .models import (
    CalibrationParams,
    InterpolatedMWResult,
    InterpolationMethodType,
    InterpolationWeight,
    LadderCalibrationData,
    MultiLadderCalibrationResult,
)
from .service import CalibrationService

logger = get_logger(__name__)


class MultiLadderCalibrationService:
    """
    Position-aware MW estimation with linear interpolation between ladder lanes.

    This service enables gel smile correction by:
    1. Calibrating all ladder lanes with the same template
    2. Storing calibrations with X position for interpolation
    3. Estimating MW using weighted interpolation from nearest ladders

    Usage:
        service = MultiLadderCalibrationService(analysis)

        # Calibrate all ladders
        result = service.calibrate_all_ladders(template, user)

        # Estimate MW for a band
        mw_result = service.estimate_mw_at_position(
            position_y=300,
            lane_x_center=500,
            lane_top=100,
            lane_bottom=800,
        )

        # Apply to all bands
        stats = service.apply_calibration_to_all_bands(user)
    """

    def __init__(self, analysis: GelAnalysis):
        """
        Initialize with a GelAnalysis.

        Args:
            analysis: GelAnalysis model instance
        """
        self.analysis = analysis
        self._calibration_service = CalibrationService()
        self._calibrations: list[LadderCalibrationData] = []
        self._load_calibrations()

    def _load_calibrations(self):
        """Load existing calibrations from database, sorted by X position."""

        self._calibrations = []

        for cal in self.analysis.ladder_calibrations.select_related("ladder_lane").order_by("ladder_x_position"):
            if cal.ladder_lane is None:
                continue

            self._calibrations.append(
                LadderCalibrationData(
                    calibration_id=str(cal.id),
                    ladder_x_position=cal.ladder_x_position,
                    method=cal.method,
                    coefficients=cal.coefficients,
                    r_squared=cal.r_squared,
                    lane_id=cal.ladder_lane.id,
                    lane_top=cal.ladder_lane.y,
                    lane_bottom=cal.ladder_lane.y + cal.ladder_lane.height,
                    band_matches=cal.band_matches or [],
                    excluded_band_ids=cal.excluded_band_ids or [],
                )
            )

        logger.debug(f"Loaded {len(self._calibrations)} calibrations for analysis {self.analysis.pk}")

    def calibrate_all_ladders(
        self,
        template: LadderTemplate,
        user: User,
        method: str = "LOG_LINEAR",
        excluded_band_ids: list[str] | None = None,
    ) -> MultiLadderCalibrationResult:
        """
        Calibrate all ladder lanes in the analysis with the same template.

        This is the main entry point for multi-ladder calibration. It:
        1. Finds all LADDER lanes in the analysis
        2. Matches bands to template for each (skipping any in excluded_band_ids)
        3. Computes calibration curve for each
        4. Saves calibrations with X positions and the excluded list (so a
           reload of the modal restores the user's selection)
        5. Creates/updates MultiLadderCalibrationConfig

        Args:
            template: LadderTemplate to use for all ladders
            user: User performing the calibration
            method: Calibration method (LOG_LINEAR, POLYNOMIAL_2, etc.)
            excluded_band_ids: Ladder band UUIDs (str) the user wants to
                drop from the fit — typically high-residual outliers spotted
                in the marker table. Each ID is matched against the band's
                primary key, so a single shared list works across all ladder
                lanes (a band only ever lives in one lane).

        Returns:
            MultiLadderCalibrationResult with all calibration results
        """
        from gel_analyzer.models import (
            InterpolationMethod,
            LadderCalibration,
            MultiLadderCalibrationConfig,
        )

        # Find all ladder lanes
        ladder_lanes = list(self.analysis.lanes.filter(lane_type="LADDER").order_by("x"))

        if not ladder_lanes:
            return MultiLadderCalibrationResult(
                success=False,
                errors=[{"message": "No ladder lanes found in analysis"}],
            )

        logger.info(f"Calibrating {len(ladder_lanes)} ladder lanes with template {template.name}")

        # Delete existing calibrations for this analysis
        self.analysis.ladder_calibrations.all().delete()

        # Calibrate each ladder
        calibration_results = []
        calibration_models = []
        errors = []
        all_warnings = []

        params = CalibrationParams(method=method)
        calibration_service = CalibrationService(params)

        excluded = list(excluded_band_ids or [])

        for lane in ladder_lanes:
            try:
                # Get bands with assigned MW values (priority over template matching),
                # skipping any IDs the user explicitly excluded.
                matches, match_warnings = calibration_service.get_bands_with_assigned_mw(
                    lane, excluded_band_ids=excluded
                )
                all_warnings.extend(match_warnings)

                if len(matches) < params.min_bands:
                    errors.append(
                        {
                            "lane_id": lane.id,
                            "lane_number": lane.lane_number,
                            "message": f"Only {len(matches)} bands with MW assigned (need {params.min_bands}). "
                            f"Assign MW values in the Band Editor first.",
                        }
                    )
                    continue

                # Compute calibration using bands with existing MW values
                result = calibration_service.calibrate(lane, template, matches, match_warnings)

                if not result.success:
                    errors.append(
                        {
                            "lane_id": lane.id,
                            "lane_number": lane.lane_number,
                            "message": result.error_message,
                        }
                    )
                    continue

                # Calculate X center
                x_center = lane.x + (lane.width // 2)

                # Save calibration. Persist the per-ladder slice of the
                # excluded list so a re-open of the modal restores the same
                # selection without forcing the user to redo the picking.
                lane_band_ids = {str(b_id) for b_id in lane.bands.values_list("id", flat=True)}
                excluded_for_lane = [b for b in excluded if b in lane_band_ids]

                calibration = LadderCalibration.objects.create(
                    analysis=self.analysis,
                    ladder_lane=lane,
                    template=template,
                    method=result.method,
                    coefficients=result.coefficients,
                    r_squared=result.r_squared,
                    matched_band_count=len(result.band_matches),
                    band_matches=[m.to_dict() for m in result.band_matches],
                    excluded_band_ids=excluded_for_lane,
                    ladder_x_position=x_center,
                    created_by=user,
                )

                calibration_results.append(result)
                calibration_models.append(calibration)

                # Collect warnings from calibration result
                if result.warnings:
                    all_warnings.extend(result.warnings)

                logger.info(
                    f"Calibrated ladder lane {lane.lane_number} (X={x_center}): "
                    f"R²={result.r_squared:.4f}, {len(matches)} bands"
                )

            except Exception as e:
                logger.exception(f"Failed to calibrate lane {lane.id}: {e}")
                errors.append(
                    {
                        "lane_id": lane.id,
                        "lane_number": lane.lane_number,
                        "message": str(e),
                    }
                )

        # Create or update MultiLadderCalibrationConfig
        config, _ = MultiLadderCalibrationConfig.objects.update_or_create(
            analysis=self.analysis,
            defaults={
                "template": template,
                "interpolation_method": InterpolationMethod.LINEAR,
                "ladder_count": len(calibration_models),
                "is_calibrated": len(calibration_models) > 0,
                "created_by": user,
            },
        )

        # Reload calibrations
        self._load_calibrations()

        # Calculate average R²
        avg_r2 = 0.0
        if calibration_results:
            avg_r2 = sum(r.r_squared for r in calibration_results) / len(calibration_results)

        # Deduplicate warnings
        unique_warnings = list(dict.fromkeys(all_warnings))

        return MultiLadderCalibrationResult(
            success=len(calibration_models) > 0,
            template_id=str(template.id),
            template_name=template.name,
            calibrations=calibration_results,
            errors=errors,
            ladder_count=len(calibration_models),
            average_r_squared=avg_r2,
            warnings=unique_warnings,
        )

    def find_nearest_ladders(
        self,
        sample_x: int,
    ) -> tuple[LadderCalibrationData | None, LadderCalibrationData | None]:
        """
        Find the left and right bracketing ladders for a sample X position.

        Args:
            sample_x: X center of the sample lane

        Returns:
            Tuple of (left_ladder, right_ladder) where either can be None
            if sample is at an edge.
        """
        if not self._calibrations:
            return None, None

        left = None
        right = None

        for cal in self._calibrations:
            if cal.ladder_x_position <= sample_x:
                left = cal
            elif right is None:
                right = cal

        return left, right

    def calculate_interpolation_weights(
        self,
        sample_x: int,
        left_ladder: LadderCalibrationData | None,
        right_ladder: LadderCalibrationData | None,
    ) -> tuple[list[InterpolationWeight], str]:
        """
        Calculate interpolation weights for the given sample position.

        Linear interpolation formula:
        weight_left = distance_to_right / total_distance
        weight_right = distance_to_left / total_distance

        Args:
            sample_x: X center of the sample lane
            left_ladder: Left bracketing ladder (or None)
            right_ladder: Right bracketing ladder (or None)

        Returns:
            Tuple of (list of InterpolationWeight, method used)
        """
        # No calibrations
        if left_ladder is None and right_ladder is None:
            return [], InterpolationMethodType.SINGLE

        # Sample is left of all ladders -> use rightmost (which is right_ladder here)
        if left_ladder is None:
            return [
                InterpolationWeight(
                    calibration_id=right_ladder.calibration_id,
                    weight=1.0,
                    ladder_x=right_ladder.ladder_x_position,
                )
            ], InterpolationMethodType.EDGE

        # Sample is right of all ladders -> use leftmost (which is left_ladder here)
        if right_ladder is None:
            return [
                InterpolationWeight(
                    calibration_id=left_ladder.calibration_id,
                    weight=1.0,
                    ladder_x=left_ladder.ladder_x_position,
                )
            ], InterpolationMethodType.EDGE

        # Sample is between two ladders -> interpolate
        total_distance = right_ladder.ladder_x_position - left_ladder.ladder_x_position

        if total_distance == 0:
            # Both ladders at same position (shouldn't happen)
            return [
                InterpolationWeight(
                    calibration_id=left_ladder.calibration_id,
                    weight=1.0,
                    ladder_x=left_ladder.ladder_x_position,
                )
            ], InterpolationMethodType.SINGLE

        # Linear interpolation weights
        # weight_left = distance_to_right / total
        # weight_right = distance_to_left / total
        distance_to_left = sample_x - left_ladder.ladder_x_position
        distance_to_right = right_ladder.ladder_x_position - sample_x

        weight_left = distance_to_right / total_distance
        weight_right = distance_to_left / total_distance

        return [
            InterpolationWeight(
                calibration_id=left_ladder.calibration_id,
                weight=weight_left,
                ladder_x=left_ladder.ladder_x_position,
            ),
            InterpolationWeight(
                calibration_id=right_ladder.calibration_id,
                weight=weight_right,
                ladder_x=right_ladder.ladder_x_position,
            ),
        ], InterpolationMethodType.LINEAR

    def estimate_mw_at_position(
        self,
        position_y: int,
        lane_x_center: int,
        lane_top: int,
        lane_bottom: int,
    ) -> InterpolatedMWResult | None:
        """
        Estimate MW using weighted interpolation from nearest ladders.

        This is the core method for gel smile correction. It:
        1. Finds bracketing ladders based on X position
        2. Calculates interpolation weights
        3. Estimates MW from each ladder
        4. Computes weighted average

        Args:
            position_y: Y position of band in pixels
            lane_x_center: X center of the sample lane
            lane_top: Y position of lane top (for Rf calculation)
            lane_bottom: Y position of lane bottom

        Returns:
            InterpolatedMWResult or None if no calibrations available
        """
        if not self._calibrations:
            return None

        # Single calibration case
        if len(self._calibrations) == 1:
            cal = self._calibrations[0]
            mw = cal.estimate_mw(position_y)
            if mw is None:
                return None

            return InterpolatedMWResult(
                estimated_mw_kda=mw,
                method=InterpolationMethodType.SINGLE,
                interpolation_weights=[
                    InterpolationWeight(
                        calibration_id=cal.calibration_id,
                        weight=1.0,
                        ladder_x=cal.ladder_x_position,
                    )
                ],
                confidence=cal.r_squared,
            )

        # Find bracketing ladders
        left, right = self.find_nearest_ladders(lane_x_center)
        weights, method = self.calculate_interpolation_weights(lane_x_center, left, right)

        if not weights:
            return None

        # Calculate MW from each ladder and interpolate
        mw_left = None
        mw_right = None
        weighted_mw = 0.0
        confidence = 0.0

        for weight in weights:
            # Find the calibration data
            cal = next((c for c in self._calibrations if c.calibration_id == weight.calibration_id), None)
            if cal is None:
                continue

            mw = cal.estimate_mw(position_y)
            if mw is None:
                continue

            # Track individual MWs for logging
            if cal == left:
                mw_left = mw
            elif cal == right:
                mw_right = mw

            # Accumulate weighted MW
            weighted_mw += mw * weight.weight
            confidence += cal.r_squared * weight.weight

        if weighted_mw == 0:
            return None

        return InterpolatedMWResult(
            estimated_mw_kda=weighted_mw,
            method=method,
            interpolation_weights=weights,
            left_ladder_mw=mw_left,
            right_ladder_mw=mw_right,
            confidence=confidence,
        )

    def apply_calibration_to_all_bands(
        self,
        user: User,
    ) -> dict:
        """
        Apply multi-ladder calibration to all bands in non-ladder lanes.

        Updates estimated_mw_kda for each band using position-aware interpolation.

        Args:
            user: User performing the operation

        Returns:
            Dict with statistics: {bands_updated, bands_failed, bands_total}
        """
        if not self._calibrations:
            logger.warning("No calibrations available to apply")
            return {"bands_updated": 0, "bands_failed": 0, "bands_total": 0}

        bands_updated = 0
        bands_failed = 0
        bands_total = 0

        # Get all non-ladder lanes
        sample_lanes = self.analysis.lanes.exclude(lane_type="LADDER")

        for lane in sample_lanes:
            lane_x_center = lane.x + (lane.width // 2)
            lane_top = lane.y
            lane_bottom = lane.y + lane.height

            for band in lane.bands.all():
                bands_total += 1

                result = self.estimate_mw_at_position(
                    position_y=band.position_y,
                    lane_x_center=lane_x_center,
                    lane_top=lane_top,
                    lane_bottom=lane_bottom,
                )

                if result is None or result.estimated_mw_kda is None:
                    bands_failed += 1
                    continue

                # Update band (round MW to 2 decimal places for cleaner display)
                band.estimated_mw_kda = round(result.estimated_mw_kda, 2)
                band.mw_estimation_method = f"MULTI_{result.method}"
                band.save(update_fields=["estimated_mw_kda", "mw_estimation_method"])
                bands_updated += 1

        logger.info(
            f"Applied multi-ladder calibration: {bands_updated}/{bands_total} bands updated, {bands_failed} failed"
        )

        return {
            "bands_updated": bands_updated,
            "bands_failed": bands_failed,
            "bands_total": bands_total,
        }

    def get_calibration_summary(self) -> dict:
        """
        Get a summary of current calibration status.

        Returns:
            Dict with calibration info for API response
        """
        from gel_analyzer.models import MultiLadderCalibrationConfig

        try:
            config = self.analysis.multi_ladder_config
        except MultiLadderCalibrationConfig.DoesNotExist:
            config = None

        # Add template bands for MW line visualization
        template_bands = []
        if config and config.template:
            template_bands = [
                {"order": b.band_order, "mw_kda": float(b.mw_kda), "name": getattr(b, "name", "") or ""}
                for b in config.template.bands.all().order_by("band_order")
            ]

        return {
            "is_calibrated": config.is_calibrated if config else False,
            "ladder_count": len(self._calibrations),
            "template_id": str(config.template.id) if config and config.template else None,
            "template_name": config.template.name if config and config.template else None,
            "template_bands": template_bands,
            "interpolation_method": config.interpolation_method if config else None,
            "calibrations": [cal.to_dict() for cal in self._calibrations],
        }

    def delete_calibration(self) -> int:
        """
        Delete all calibrations for this analysis.

        Returns:
            Number of calibrations deleted
        """
        import contextlib

        from gel_analyzer.models import MultiLadderCalibrationConfig

        # Delete calibrations
        count = self.analysis.ladder_calibrations.all().delete()[0]

        # Delete config
        with contextlib.suppress(MultiLadderCalibrationConfig.DoesNotExist):
            self.analysis.multi_ladder_config.delete()

        # Clear cached data
        self._calibrations = []

        logger.info(f"Deleted {count} calibrations for analysis {self.analysis.pk}")

        return count
