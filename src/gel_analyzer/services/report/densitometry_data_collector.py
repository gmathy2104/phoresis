"""
Data collector for densitometry report generation.

Queries GelAnalysis and related models, returns structured dataclasses for report generation.
Reuses LaneReportData, BandReportData, CalibrationReportData from data_collector.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gel_analyzer.models import (
    GelAnalysis,
    LaneDensitometrySummary,
)
from phoresis_core.logging_config import get_logger

from .data_collector import (
    CalibrationReportData,
    LaneReportData,
    ReportDataCollector,
)

logger = get_logger(__name__)


@dataclass
class DensitometryReportData:
    """Complete densitometry report data structure."""

    # Analysis metadata
    analysis_id: str
    analysis_name: str
    analysis_status: str
    gel_type: str
    notes: str
    created_by_name: str
    created_at: str

    # Image info
    image_title: str
    image_width: int | None
    image_height: int | None
    gel_image_id: int | None = None

    # Lanes
    lanes: list[LaneReportData] = field(default_factory=list)

    # Calibrations
    calibrations: list[CalibrationReportData] = field(default_factory=list)
    has_calibration: bool = False

    # Multi-ladder info
    multi_ladder_enabled: bool = False
    multi_ladder_template: str | None = None
    multi_ladder_interpolation: str | None = None

    # Gel-level counts
    total_lanes_count: int = 0
    total_bands_count: int = 0

    # Densitometry aggregations
    average_purity: float | None = None
    densitometry_computed_at: str | None = None

    # Report metadata
    report_generated_at: str = ""
    report_generated_by: str = ""
    software_version: str = "GelAnalyzer v1.0"


class DensitometryDataCollector:
    """
    Collects and structures data from GelAnalysis models for densitometry report generation.

    Extends the base ReportDataCollector pattern with densitometry-specific aggregations.
    """

    def __init__(self):
        pass

    def collect(self, analysis: GelAnalysis, user) -> DensitometryReportData:
        """
        Collect all report data for the given analysis.

        Args:
            analysis: GelAnalysis instance to collect data from
            user: User generating the report

        Returns:
            DensitometryReportData instance with all structured data
        """

        logger.info(f"Collecting densitometry report data for analysis {analysis.id}")

        # Reuse base collector for lane/band/calibration data
        base_collector = ReportDataCollector()
        base_data = base_collector.collect(analysis, user)

        # Get gel image ID
        gel_image_id = None
        if hasattr(analysis, "gel_image") and analysis.gel_image:
            gel_image_id = analysis.gel_image.pk

        # Compute densitometry aggregations
        purity_values = [lane.poi_percentage for lane in base_data.lanes if lane.poi_percentage is not None]
        average_purity = sum(purity_values) / len(purity_values) if purity_values else None

        # Get latest densitometry computation timestamp
        densitometry_computed_at = None
        try:
            latest_summary = (
                LaneDensitometrySummary.objects.filter(lane__analysis=analysis).order_by("-computed_at").first()
            )
            if latest_summary and latest_summary.computed_at:
                densitometry_computed_at = latest_summary.computed_at.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            logger.warning(f"Failed to get densitometry timestamp: {e}")

        # Build densitometry report data
        report_data = DensitometryReportData(
            # Analysis metadata
            analysis_id=base_data.analysis_id,
            analysis_name=base_data.analysis_name,
            analysis_status=base_data.analysis_status,
            gel_type=base_data.gel_type,
            notes=base_data.notes,
            created_by_name=base_data.created_by_name,
            created_at=base_data.created_at,
            # Image info
            image_title=base_data.image_title,
            image_width=base_data.image_width,
            image_height=base_data.image_height,
            gel_image_id=gel_image_id,
            # Lanes
            lanes=base_data.lanes,
            # Calibrations
            calibrations=base_data.calibrations,
            has_calibration=base_data.has_calibration,
            # Multi-ladder
            multi_ladder_enabled=base_data.multi_ladder_enabled,
            multi_ladder_template=base_data.multi_ladder_template,
            multi_ladder_interpolation=base_data.multi_ladder_interpolation,
            # Counts
            total_lanes_count=base_data.total_lanes_count,
            total_bands_count=base_data.total_bands_count,
            # Densitometry aggregations
            average_purity=average_purity,
            densitometry_computed_at=densitometry_computed_at,
            # Report metadata
            report_generated_at=base_data.report_generated_at,
            report_generated_by=base_data.report_generated_by,
            software_version=base_data.software_version,
        )

        logger.info(
            f"Collected densitometry data: {report_data.total_lanes_count} lanes, "
            f"{report_data.total_bands_count} bands, avg purity={average_purity}"
        )

        return report_data
