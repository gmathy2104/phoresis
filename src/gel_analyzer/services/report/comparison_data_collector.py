"""
Data collector for gel lane comparison reports.

Queries SavedComparison and related models, returns structured dataclasses for report generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gel_analyzer.models import (
    LadderCalibration,
    Lane,
    SavedComparison,
    SavedComparisonLane,
)
from phoresis_core.logging_config import get_logger

from .data_collector import BandReportData, LaneReportData

logger = get_logger(__name__)


@dataclass
class ComparisonLaneData(LaneReportData):
    """
    Lane data extended with comparison-specific metadata.

    Inherits all LaneReportData fields and adds:
    - Source analysis information (name, ID, gel type)
    - Calibration status
    - Display order
    """

    # Source analysis info
    analysis_id: str = ""
    analysis_name: str = ""
    gel_type: str = ""
    image_title: str = ""

    # Calibration info
    has_calibration: bool = False
    calibration_method: str = ""
    calibration_r_squared: float | None = None

    # Display order
    order: int = 0

    # Gel image reference for server-side image loading
    gel_image_id: int | None = None


@dataclass
class ComparisonReportData:
    """Complete comparison report data structure."""

    # Comparison metadata
    comparison_id: str
    name: str
    description: str
    is_public: bool

    # Lanes in comparison (ordered)
    lanes: list[ComparisonLaneData] = field(default_factory=list)
    lane_count: int = 0

    # Aggregated metadata
    gel_types: list[str] = field(default_factory=list)
    calibrated_count: int = 0
    all_calibrated: bool = False

    # Audit
    created_by_name: str = ""
    created_at: str = ""

    # Settings
    mw_tolerance_pct: float = 5.0

    # Report metadata
    report_generated_at: str = ""
    report_generated_by: str = ""
    software_version: str = "GelAnalyzer v1.0"


class ComparisonDataCollector:
    """
    Collects and structures data from SavedComparison models for report generation.
    """

    def __init__(self):
        """Initialize the comparison data collector."""
        pass

    def collect(self, comparison: SavedComparison, user) -> ComparisonReportData:
        """
        Collect all report data for the given comparison.

        Args:
            comparison: SavedComparison instance to collect data from
            user: User generating the report

        Returns:
            ComparisonReportData instance with all structured data
        """
        from django.utils import timezone

        logger.info(f"Collecting comparison report data for {comparison.id}")

        # Query comparison lanes in order with all related data
        comparison_lanes = (
            SavedComparisonLane.objects.filter(saved_comparison=comparison)
            .select_related("lane", "lane__analysis", "lane__analysis__gel_image", "lane__densitometry_summary")
            .prefetch_related("lane__bands", "lane__bands__densitometry")
            .order_by("order")
        )

        # Collect calibration data for each unique analysis
        analysis_calibrations = {}
        unique_analysis_ids = set()

        for comp_lane in comparison_lanes:
            lane = comp_lane.lane
            if lane.analysis:
                analysis_id = lane.analysis.id
                if analysis_id not in unique_analysis_ids:
                    unique_analysis_ids.add(analysis_id)
                    try:
                        calibration = (
                            LadderCalibration.objects.filter(analysis=lane.analysis).select_related("template").first()
                        )

                        if calibration:
                            analysis_calibrations[analysis_id] = {
                                "method": calibration.get_method_display(),
                                "r_squared": calibration.r_squared,
                                "template_name": calibration.template.name if calibration.template else None,
                            }
                    except Exception as e:
                        logger.warning(f"Failed to get calibration for analysis {analysis_id}: {e}")

        # Build lane data list
        lane_data_list = []
        gel_types_set = set()
        calibrated_count = 0

        for comp_lane in comparison_lanes:
            lane = comp_lane.lane
            analysis = lane.analysis

            # Get base lane data using helper
            base_lane_data = self._build_lane_data(lane)

            # Get analysis info
            analysis_id = str(analysis.id) if analysis else ""
            analysis_name = analysis.name or "Unnamed Analysis" if analysis else "N/A"

            gel_type = "N/A"
            image_title = "N/A"
            gel_image_id = None
            if analysis and hasattr(analysis, "gel_image") and analysis.gel_image:
                gel_type = (
                    analysis.gel_image.get_gel_type_display() if hasattr(analysis.gel_image, "gel_type") else "N/A"
                )
                image_title = analysis.gel_image.original_filename or "Unnamed Image"
                gel_image_id = analysis.gel_image.pk
                gel_types_set.add(gel_type)

            # Get calibration info
            has_calibration = False
            calibration_method = ""
            calibration_r_squared = None

            if analysis and analysis.id in analysis_calibrations:
                has_calibration = True
                cal_data = analysis_calibrations[analysis.id]
                calibration_method = cal_data["method"]
                calibration_r_squared = cal_data["r_squared"]
                calibrated_count += 1

            # Create ComparisonLaneData (extends LaneReportData)
            comparison_lane_data = ComparisonLaneData(
                # Base fields from LaneReportData
                lane_id=base_lane_data.lane_id,
                lane_number=base_lane_data.lane_number,
                lane_type=base_lane_data.lane_type,
                sample_name=base_lane_data.sample_name,
                condition=base_lane_data.condition,
                protein_load_ug=base_lane_data.protein_load_ug,
                protein_load_type=base_lane_data.protein_load_type,
                notes=base_lane_data.notes,
                x=base_lane_data.x,
                y=base_lane_data.y,
                width=base_lane_data.width,
                height=base_lane_data.height,
                lane_type_code=base_lane_data.lane_type_code,
                lane_shape=base_lane_data.lane_shape,
                polygon=base_lane_data.polygon,
                bands=base_lane_data.bands,
                total_integrated_area=base_lane_data.total_integrated_area,
                poi_integrated_area=base_lane_data.poi_integrated_area,
                poi_percentage=base_lane_data.poi_percentage,
                band_count=base_lane_data.band_count,
                poi_band_count=base_lane_data.poi_band_count,
                profile_data=base_lane_data.profile_data,
                # Additional comparison fields
                analysis_id=analysis_id,
                analysis_name=analysis_name,
                gel_type=gel_type,
                image_title=image_title,
                has_calibration=has_calibration,
                calibration_method=calibration_method,
                calibration_r_squared=calibration_r_squared,
                order=comp_lane.order,
                gel_image_id=gel_image_id,
            )

            lane_data_list.append(comparison_lane_data)

        # Build report data
        gel_types_list = sorted(gel_types_set)

        # Read MW tolerance from view settings
        mw_tolerance = 5.0
        if comparison.view_settings:
            mw_tolerance = float(comparison.view_settings.get("mw_tolerance", 5))

        report_data = ComparisonReportData(
            # Comparison metadata
            comparison_id=str(comparison.id),
            name=comparison.name,
            description=comparison.description,
            is_public=comparison.is_public,
            # Lanes
            lanes=lane_data_list,
            lane_count=len(lane_data_list),
            # Aggregated metadata
            gel_types=gel_types_list,
            calibrated_count=calibrated_count,
            all_calibrated=(calibrated_count == len(lane_data_list)) if lane_data_list else False,
            # Settings
            mw_tolerance_pct=mw_tolerance,
            # Audit
            created_by_name=comparison.created_by.get_full_name() if comparison.created_by else "Unknown",
            created_at=comparison.created_at.strftime("%Y-%m-%d %H:%M") if comparison.created_at else "",
            # Report metadata
            report_generated_at=timezone.now().strftime("%B %d, %Y at %H:%M"),
            report_generated_by=user.get_full_name() if hasattr(user, "get_full_name") else str(user),
            software_version="GelAnalyzer v1.0",
        )

        logger.info(
            f"Collected comparison data: {report_data.lane_count} lanes, "
            f"{calibrated_count} calibrated, gel types: {', '.join(gel_types_list)}"
        )

        return report_data

    def _build_lane_data(self, lane: Lane) -> LaneReportData:
        """
        Build LaneReportData from Lane model instance.
        Reuses logic from ReportDataCollector.

        Args:
            lane: Lane instance

        Returns:
            LaneReportData with bands and densitometry
        """
        from gel_analyzer.models import LaneDensitometrySummary

        # Get sample name
        # Phoresis has no ProcessSample registry.
        sample_name = lane.sample_name or lane.get_lane_type_display()

        # Build bands
        bands = []
        for band in lane.bands.order_by("position_y"):
            band_data = self._build_band_data(band)
            bands.append(band_data)

        # Get densitometry summary
        total_area = None
        poi_area = None
        poi_pct = None
        band_count = 0
        poi_band_count = 0
        profile_data = None

        try:
            summary = lane.densitometry_summary
            total_area = summary.total_integrated_area
            poi_area = summary.poi_integrated_area
            poi_pct = summary.poi_percentage
            band_count = summary.band_count
            poi_band_count = summary.poi_band_count
            profile_data = summary.profile_data
        except LaneDensitometrySummary.DoesNotExist:
            pass

        # Enrich profile_data with MW values if calibration is available.
        # Rf is computed in the LADDER lane's reference frame.
        if profile_data and lane.analysis:
            try:
                calibration = lane.analysis.ladder_calibrations.first()
                if calibration and calibration.ladder_lane:
                    y_positions = profile_data.get("y_positions", [])
                    ladder_top = calibration.ladder_lane.y
                    ladder_bottom = calibration.ladder_lane.y + calibration.ladder_lane.height
                    if y_positions and ladder_bottom > ladder_top:
                        mw_values = []
                        for y_pos in y_positions:
                            mw = calibration.estimate_mw(int(y_pos), ladder_top, ladder_bottom)
                            mw_values.append(float(mw) if mw else None)
                        if any(v is not None for v in mw_values):
                            profile_data = dict(profile_data)
                            profile_data["mw_values"] = mw_values
            except Exception:
                pass

        return LaneReportData(
            lane_id=lane.id,
            lane_number=lane.lane_number,
            lane_type=lane.get_lane_type_display(),
            sample_name=sample_name,
            condition=lane.condition_display,
            protein_load_ug=lane.protein_load_ug,
            protein_load_type=lane.get_protein_load_type_display() if lane.protein_load_type else "",
            notes=lane.notes,
            x=lane.x,
            y=lane.y,
            width=lane.width,
            height=lane.height,
            lane_type_code=lane.lane_type or "SAMPLE",
            lane_shape=getattr(lane, "lane_shape", "RECTANGLE") or "RECTANGLE",
            polygon=getattr(lane, "polygon", None) or None,
            bands=bands,
            total_integrated_area=total_area,
            poi_integrated_area=poi_area,
            poi_percentage=poi_pct,
            band_count=band_count,
            poi_band_count=poi_band_count,
            profile_data=profile_data,
        )

    def _build_band_data(self, band) -> BandReportData:
        """
        Build BandReportData from Band model instance.
        Reuses logic from ReportDataCollector.

        Args:
            band: Band instance

        Returns:
            BandReportData with densitometry results
        """
        from gel_analyzer.models import DensitometryResult

        # Get densitometry if available
        corrected_area = None
        peak_amplitude = None
        peak_sigma = None
        fwhm = None
        fit_r_squared = None
        snr = None
        relative_pct_lane = None
        relative_pct_gel = None
        fit_quality = None

        try:
            densitometry = band.densitometry
            corrected_area = densitometry.corrected_area
            peak_amplitude = densitometry.peak_amplitude
            peak_sigma = densitometry.peak_sigma
            fwhm = densitometry.fwhm
            fit_r_squared = densitometry.fit_r_squared
            snr = densitometry.snr
            relative_pct_lane = densitometry.relative_percent_lane
            relative_pct_gel = densitometry.relative_percent_gel
            fit_quality = densitometry.fit_quality
        except DensitometryResult.DoesNotExist:
            pass

        return BandReportData(
            band_id=str(band.id),
            band_type=band.get_band_type_display(),
            band_type_code=band.band_type or "OTHER",
            band_number=band.band_number,
            position_y=band.position_y,
            estimated_mw_kda=band.estimated_mw_kda,
            label=band.label,
            bbox_x=band.bbox_x,
            bbox_y=band.bbox_y,
            bbox_width=band.bbox_width,
            bbox_height=band.bbox_height,
            polygon=getattr(band, "polygon", None) or None,
            corrected_area=corrected_area,
            peak_amplitude=peak_amplitude,
            peak_sigma=peak_sigma,
            fwhm=fwhm,
            fit_r_squared=fit_r_squared,
            snr=snr,
            relative_percent_lane=relative_pct_lane,
            relative_percent_gel=relative_pct_gel,
            fit_quality=fit_quality,
        )
