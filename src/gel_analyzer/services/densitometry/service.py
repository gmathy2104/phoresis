"""
Densitometry service orchestrator.

Main entry point for densitometry analysis. Coordinates:
- Intensity profile extraction (reuses band_detection services)
- Peak integration (Gaussian fitting)
- Normalization (relative quantification)
- Purity calculations
- Database persistence

Usage:
    from gel_analyzer.services.densitometry import DensitometryService

    service = DensitometryService()
    result = service.analyze_analysis(analysis, image)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np

from django.db import transaction

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from gel_analyzer.models import GelAnalysis, Lane

from gel_analyzer.services.band_detection import (
    BandDetectionParams,
    IntensityProfile,
)
from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor

from .models import (
    DensitometryAnalysisResult,
    DensitometryParams,
    LaneDensitometryResultData,
    LaneProfileData,
)
from .normalizer import DensitometryNormalizer, compute_gel_statistics
from .peak_integrator import PeakIntegrator
from .purity_calculator import PurityCalculator

logger = get_logger(__name__)


class DensitometryService:
    """
    Main orchestrator for densitometry analysis.

    Provides methods to analyze individual lanes or entire gel analyses,
    with options for preview (no save) or persistent mode.

    Usage:
        service = DensitometryService(params)

        # Preview mode (no database changes)
        result = service.analyze_analysis(analysis, image)

        # Persistent mode
        result = service.analyze_and_save(analysis, image, user)
    """

    def __init__(self, params: DensitometryParams | None = None):
        """
        Initialize service with parameters.

        Args:
            params: Densitometry parameters. If None, uses defaults.
        """
        self.params = params or DensitometryParams()

        # Initialize sub-services
        # Reuse band detection params for profile extraction
        band_params = BandDetectionParams(
            smoothing_window=self.params.smoothing_window,
            smoothing_polyorder=self.params.smoothing_polyorder,
            rolling_ball_radius=self.params.rolling_ball_radius,
            profile_width_percent=self.params.profile_width_percent,
        )

        self.profile_extractor = IntensityProfileExtractor(band_params)
        self.profile_processor = ProfileProcessor(band_params)
        self.peak_integrator = PeakIntegrator(self.params)
        self.normalizer = DensitometryNormalizer(self.params)
        self.purity_calculator = PurityCalculator()

    def analyze_lane(
        self,
        lane: Lane,
        image: np.ndarray,
        calibration_data: dict | None = None,
    ) -> LaneDensitometryResultData:
        """
        Analyze a single lane for densitometry.

        Args:
            lane: Lane model instance with bands.
            image: Gel image as numpy array.
            calibration_data: Optional MW calibration data for MW axis.

        Returns:
            LaneDensitometryResultData with all peak integration results.
        """
        start_time = time.time()

        result = LaneDensitometryResultData(
            lane_id=lane.id,
            lane_number=lane.lane_number,
            lane_type=lane.lane_type,
        )

        try:
            # Get bands for this lane
            bands = list(lane.bands.all().order_by("position_y"))

            if not bands:
                logger.warning(f"Lane {lane.lane_number}: no bands to analyze")
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # Extract intensity profile
            profile = self.profile_extractor.extract_profile(image, lane)

            if profile.is_empty:
                logger.warning(f"Lane {lane.lane_number}: empty profile")
                result.success = False
                result.error_message = "Failed to extract intensity profile"
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # Process profile (smoothing + background subtraction)
            profile = self.profile_processor.process(profile)

            # Store profile data for visualization
            result.profile_data = self._create_profile_data(profile, lane, calibration_data)

            # Get background array for integration
            background = np.array(profile.background) if profile.background else None

            # Integrate each band
            peaks = self.peak_integrator.integrate_bands(bands, profile, background)

            result.peaks = peaks
            result.bands_processed = len(bands)
            result.bands_successful = sum(1 for p in peaks if p.fit_successful or p.corrected_area > 0)

            # Apply normalization
            self.normalizer.normalize_lane(result)

            result.success = True

        except Exception as e:
            logger.exception(f"Error analyzing lane {lane.lane_number}: {e}")
            result.success = False
            result.error_message = str(e)

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.debug(
            f"Lane {lane.lane_number}: {result.bands_processed} bands, "
            f"{result.bands_successful} successful, "
            f"purity={result.poi_percentage:.1f}%"
            if result.poi_percentage
            else "N/A",
            f" ({result.processing_time_ms:.0f}ms)",
        )

        return result

    def analyze_analysis(
        self,
        analysis: GelAnalysis,
        image: np.ndarray,
        lane_ids: list[int] | None = None,
        progress_callback: callable | None = None,
    ) -> DensitometryAnalysisResult:
        """
        Analyze all lanes in a GelAnalysis.

        Args:
            analysis: GelAnalysis model instance.
            image: Gel image as numpy array.
            lane_ids: Optional list of specific lane IDs to process.
            progress_callback: Optional callback(current, total, lane_number).

        Returns:
            DensitometryAnalysisResult with all lane results.
        """
        start_time = time.time()

        result = DensitometryAnalysisResult(
            analysis_id=str(analysis.id),
            params_used=self.params,
        )

        try:
            # Refresh analysis to ensure we see newly created bands
            # (fixes race condition when PROFILE bands are created just before task runs)
            analysis.refresh_from_db()

            # Get lanes to process
            lanes = analysis.lanes.prefetch_related("bands").all()
            if lane_ids:
                lanes = lanes.filter(id__in=lane_ids)
            lanes = list(lanes.order_by("lane_number"))

            if not lanes:
                logger.warning(f"Analysis {analysis.id}: no lanes to process")
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # Get calibration data if available
            calibration_data = self._get_calibration_data(analysis)

            # Process each lane
            lane_results = []
            for i, lane in enumerate(lanes, 1):
                if progress_callback:
                    progress_callback(i, len(lanes), lane.lane_number)

                lane_result = self.analyze_lane(lane, image, calibration_data)
                lane_results.append(lane_result)

            # Apply gel-level normalization
            lane_results = self.normalizer.normalize_gel(lane_results)

            # Compute gel statistics
            gel_stats = compute_gel_statistics(lane_results)

            # Populate result
            result.lanes = lane_results
            result.lanes_processed = len(lane_results)
            result.lanes_successful = sum(1 for r in lane_results if r.success)
            result.total_bands = sum(len(r.peaks) for r in lane_results)
            result.gel_total_area = gel_stats["gel_total_area"]
            result.average_poi_percentage = gel_stats["average_poi_percentage"]
            result.success = result.lanes_successful > 0

        except Exception as e:
            logger.exception(f"Error analyzing gel {analysis.id}: {e}")
            result.success = False
            result.error_message = str(e)

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Analysis {analysis.id}: {result.lanes_processed} lanes, "
            f"{result.total_bands} bands, {result.processing_time_ms:.0f}ms"
        )

        return result

    def analyze_and_save(
        self,
        analysis: GelAnalysis,
        image: np.ndarray,
        user: AbstractUser,
        lane_ids: list[int] | None = None,
        progress_callback: callable | None = None,
    ) -> DensitometryAnalysisResult:
        """
        Analyze and save densitometry results to database.

        Args:
            analysis: GelAnalysis model instance.
            image: Gel image as numpy array.
            user: User performing the analysis.
            lane_ids: Optional list of specific lane IDs to process.
            progress_callback: Optional callback(current, total, lane_number).

        Returns:
            DensitometryAnalysisResult with all lane results.
        """
        # Run analysis
        result = self.analyze_analysis(analysis, image, lane_ids, progress_callback)

        if not result.success:
            return result

        # Save to database
        try:
            self._save_results(result, user)
        except Exception as e:
            logger.exception(f"Error saving densitometry results: {e}")
            result.error_message = f"Analysis complete but save failed: {e}"

        return result

    @transaction.atomic
    def _save_results(
        self,
        result: DensitometryAnalysisResult,
        user: AbstractUser,
    ) -> None:
        """
        Save densitometry results to database.

        Creates/updates DensitometryResult for each band and
        LaneDensitometrySummary for each lane.

        Uses bulk operations to minimize database queries (~10 queries
        instead of ~1000+ for large analyses).

        Args:
            result: Analysis result to save.
            user: User performing the save.
        """
        from gel_analyzer.models import (
            Band,
            DensitometryResult,
            Lane,
            LaneDensitometrySummary,
        )

        # Filter successful lane results
        successful_lanes = [lr for lr in result.lanes if lr.success]
        if not successful_lanes:
            logger.warning("No successful lane results to save")
            return

        # =====================================================================
        # Phase 1: Prefetch all data upfront (2 queries instead of N)
        # =====================================================================
        lane_ids = [lr.lane_id for lr in successful_lanes]
        all_band_ids = [peak.band_id for lr in successful_lanes for peak in lr.peaks]

        # Prefetch lanes and bands in bulk
        lanes_map = {lane.id: lane for lane in Lane.objects.filter(id__in=lane_ids)}
        bands_map = {str(band.id): band for band in Band.objects.filter(id__in=all_band_ids)}

        # Prefetch existing densitometry results
        existing_densitometry = {
            str(dr.band_id): dr for dr in DensitometryResult.objects.filter(band_id__in=all_band_ids)
        }

        logger.debug(
            f"Prefetched {len(lanes_map)} lanes, {len(bands_map)} bands, "
            f"{len(existing_densitometry)} existing densitometry results"
        )

        # =====================================================================
        # Phase 2: Process lane summaries (update_or_create is OK for ~19 lanes)
        # =====================================================================
        for lane_result in successful_lanes:
            lane = lanes_map.get(lane_result.lane_id)
            if not lane:
                logger.warning(f"Lane {lane_result.lane_id} not found, skipping")
                continue

            LaneDensitometrySummary.objects.update_or_create(
                lane=lane,
                defaults={
                    "normalization_method": self.params.normalization_method.value.upper(),
                    "reference_band_id": self.params.reference_band_id,
                    "total_integrated_area": lane_result.total_integrated_area,
                    "poi_integrated_area": lane_result.poi_integrated_area,
                    "poi_percentage": lane_result.poi_percentage,
                    "other_integrated_area": lane_result.other_integrated_area,
                    "mw_reference_area": lane_result.mw_reference_area,
                    "band_count": lane_result.bands_processed,
                    "poi_band_count": sum(1 for p in lane_result.peaks if p.band_type == "POI"),
                    "profile_data": lane_result.profile_data.to_dict() if lane_result.profile_data else None,
                    "computed_by": user,
                },
            )

        # =====================================================================
        # Phase 3: Build bulk lists for DensitometryResult
        # =====================================================================
        densitometry_to_create = []
        densitometry_to_update = []
        bands_to_update = []

        for lane_result in successful_lanes:
            for peak in lane_result.peaks:
                band_id_str = str(peak.band_id)
                band = bands_map.get(band_id_str)
                if not band:
                    logger.warning(f"Band {peak.band_id} not found, skipping")
                    continue

                # Build defaults dict for this peak
                defaults = {
                    "peak_center_y": peak.peak_center,
                    "peak_amplitude": peak.amplitude,
                    "peak_sigma": peak.sigma,
                    "fwhm": peak.fwhm,
                    "integrated_area": peak.integrated_area,
                    "background_area": peak.background_area,
                    "corrected_area": peak.corrected_area,
                    "fit_r_squared": peak.fit_r_squared if peak.fit_successful else 0.0,
                    "snr": peak.snr,
                    "relative_percent_lane": peak.relative_percent_lane,
                    "relative_percent_gel": peak.relative_percent_gel,
                }

                # Check if exists -> update, else -> create
                if band_id_str in existing_densitometry:
                    dr = existing_densitometry[band_id_str]
                    for field, value in defaults.items():
                        setattr(dr, field, value)
                    densitometry_to_update.append(dr)
                else:
                    densitometry_to_create.append(DensitometryResult(band=band, **defaults))

                # Update band intensity
                band.intensity_normalized = peak.relative_percent_lane
                bands_to_update.append(band)

        # =====================================================================
        # Phase 4: Execute bulk operations (3 queries instead of 600+)
        # =====================================================================
        if densitometry_to_create:
            DensitometryResult.objects.bulk_create(densitometry_to_create)
            logger.debug(f"Bulk created {len(densitometry_to_create)} DensitometryResult records")

        if densitometry_to_update:
            DensitometryResult.objects.bulk_update(
                densitometry_to_update,
                fields=[
                    "peak_center_y",
                    "peak_amplitude",
                    "peak_sigma",
                    "fwhm",
                    "integrated_area",
                    "background_area",
                    "corrected_area",
                    "fit_r_squared",
                    "snr",
                    "relative_percent_lane",
                    "relative_percent_gel",
                ],
            )
            logger.debug(f"Bulk updated {len(densitometry_to_update)} DensitometryResult records")

        if bands_to_update:
            Band.objects.bulk_update(bands_to_update, ["intensity_normalized"])
            logger.debug(f"Bulk updated {len(bands_to_update)} Band intensity values")

        logger.info(
            f"Saved densitometry results for {len(successful_lanes)} lanes, "
            f"{len(densitometry_to_create)} created, {len(densitometry_to_update)} updated"
        )

    def _create_profile_data(
        self,
        profile: IntensityProfile,
        lane: Lane,
        calibration_data: dict | None = None,
    ) -> LaneProfileData:
        """
        Create profile data for chart visualization.

        Args:
            profile: Processed intensity profile.
            lane: Lane model for MW estimation.
            calibration_data: Optional calibration data.

        Returns:
            LaneProfileData for frontend visualization.
        """
        y_positions = profile.y_positions
        intensities = profile.processed_intensities
        background = profile.background
        raw = profile.raw_intensities

        # Convert Y positions to MW if calibration available
        mw_values = []
        if calibration_data:
            for y in y_positions:
                mw = self._estimate_mw(y, lane, calibration_data)
                mw_values.append(mw)
        else:
            mw_values = [None] * len(y_positions)

        return LaneProfileData(
            y_positions=list(y_positions),
            intensities=list(intensities),
            mw_values=mw_values,
            background=list(background) if background else [],
            raw_intensities=list(raw),
        )

    def _get_calibration_data(
        self,
        analysis: GelAnalysis,
    ) -> dict | None:
        """
        Get MW calibration data for the analysis.

        Uses multi-ladder calibration if available.

        Args:
            analysis: GelAnalysis model.

        Returns:
            Calibration data dict or None.
        """
        try:
            from gel_analyzer.services.calibration.multi_ladder_service import (
                MultiLadderCalibrationService,
            )

            service = MultiLadderCalibrationService()
            config = service.get_config(analysis)

            if config and config.is_valid:
                return {
                    "config": config,
                    "service": service,
                }
        except Exception as e:
            logger.debug(f"No calibration data available: {e}")

        return None

    def _estimate_mw(
        self,
        position_y: int,
        lane: Lane,
        calibration_data: dict | None,
    ) -> float | None:
        """
        Estimate MW for a Y position using calibration.

        Args:
            position_y: Y position in image pixels.
            lane: Lane model for position context.
            calibration_data: Calibration data dict.

        Returns:
            Estimated MW in kDa or None.
        """
        if not calibration_data:
            return None

        try:
            config = calibration_data.get("config")
            service = calibration_data.get("service")

            if config and service:
                # Get lane X center for interpolation
                bbox = lane.bbox
                lane_x = bbox["x"] + bbox["width"] // 2

                result = service.estimate_mw(
                    config=config,
                    position_y=position_y,
                    band_x=lane_x,
                )

                if result:
                    return result.estimated_mw_kda
        except Exception as e:
            logger.debug(f"MW estimation failed: {e}")

        return None
