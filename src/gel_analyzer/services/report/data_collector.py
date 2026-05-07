"""
Data collector for gel analysis reports.

Queries all models and returns structured dataclasses for report generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    GelAnalysis,
    LadderCalibration,
    Lane,
    LaneDensitometrySummary,
    MultiLadderCalibrationConfig,
)
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _user_display(user) -> str:
    """Resolve a human-readable label for a Django User to put on the
    report cover. Falls through full name → username → email → 'Unknown'.
    """
    if user is None:
        return "Unknown"
    full = getattr(user, "get_full_name", lambda: "")()
    if full and full.strip():
        return full.strip()
    for attr in ("username", "email"):
        val = getattr(user, attr, "") or ""
        if val:
            return str(val)
    return str(user) or "Unknown"


@dataclass
class BandReportData:
    """Densitometry data for a single band."""

    # Identity
    band_id: str
    band_type: str  # Display string, e.g. "Protein of Interest"
    band_number: int | None
    position_y: int
    estimated_mw_kda: float | None
    label: str

    # Geometry — bbox is the fallback shape; polygon, when present,
    # carries the actual user-drawn outline (matches Band.polygon JSON
    # field, list of [x, y] pairs in image-pixel coordinates).
    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_width: int | None = None
    bbox_height: int | None = None
    polygon: list | None = None

    # Enum code (e.g. "POI", "MW_REFERENCE", "OTHER") for palette lookups —
    # default at the end so existing positional callers stay compatible.
    band_type_code: str = "OTHER"

    # Densitometry results
    corrected_area: float | None = None
    peak_amplitude: float | None = None
    peak_sigma: float | None = None
    fwhm: float | None = None
    fit_r_squared: float | None = None
    snr: float | None = None
    relative_percent_lane: float | None = None
    relative_percent_gel: float | None = None
    fit_quality: str | None = None


@dataclass
class LaneReportData:
    """Lane data with bands and densitometry summary."""

    # Identity
    lane_id: int
    lane_number: int
    lane_type: str  # Display string ("Sample", "MW Ladder"…)
    sample_name: str
    condition: str
    protein_load_ug: float | None
    protein_load_type: str
    notes: str

    # Geometry — rectangle bbox is always populated; ``polygon`` carries
    # the actual outline when ``lane_shape != RECTANGLE``.
    x: int
    y: int
    width: int
    height: int

    # Optional fields with defaults — added in the brand refresh; placed
    # AFTER the required fields so subclass dataclasses keep working.
    lane_type_code: str = "SAMPLE"  # enum code for palette lookups
    lane_shape: str = "RECTANGLE"
    polygon: list | None = None

    # Bands
    bands: list[BandReportData] = field(default_factory=list)

    # Densitometry summary
    total_integrated_area: float | None = None
    poi_integrated_area: float | None = None
    poi_percentage: float | None = None
    band_count: int = 0
    poi_band_count: int = 0

    # Profile data for electropherogram rendering
    profile_data: dict | None = None


@dataclass
class CalibrationReportData:
    """MW calibration data for a ladder lane."""

    ladder_lane_number: int
    template_name: str
    manufacturer: str
    method: str
    equation: str
    r_squared: float
    r_squared_quality: str
    matched_band_count: int
    band_matches: list = field(default_factory=list)


@dataclass
class ReportData:
    """Complete report data structure."""

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
    gel_image_id: str | None = None  # used by server-side overlay rendering

    # Lanes
    lanes: list[LaneReportData] = field(default_factory=list)

    # Calibrations
    calibrations: list[CalibrationReportData] = field(default_factory=list)
    has_calibration: bool = False

    # Multi-ladder info
    multi_ladder_enabled: bool = False
    multi_ladder_template: str | None = None
    multi_ladder_interpolation: str | None = None

    # Gel-level densitometry summary
    total_lanes_count: int = 0
    total_bands_count: int = 0

    # Report metadata
    report_generated_at: str = ""
    report_generated_by: str = ""
    software_version: str = "GelAnalyzer v1.0"


class ReportDataCollector:
    """
    Collects and structures data from gel analysis models for report generation.
    """

    def __init__(self):
        """Initialize the data collector."""
        pass

    def collect(self, analysis: GelAnalysis, user) -> ReportData:
        """
        Collect all report data for the given analysis.

        Args:
            analysis: GelAnalysis instance to collect data from
            user: User generating the report

        Returns:
            ReportData instance with all structured data
        """
        from django.utils import timezone

        logger.info(f"Collecting report data for analysis {analysis.id}")

        # Collect lanes with related data
        lanes = (
            Lane.objects.filter(analysis=analysis)
            .prefetch_related("bands", "bands__densitometry")
            .select_related("densitometry_summary")
            .order_by("lane_number")
        )

        # Collect calibrations
        calibrations = LadderCalibration.objects.filter(analysis=analysis).select_related("template", "ladder_lane")

        # Multi-ladder config
        try:
            multi_config = MultiLadderCalibrationConfig.objects.get(analysis=analysis)
            multi_ladder_enabled = True
            multi_ladder_template = multi_config.template.name if multi_config.template else None
            multi_ladder_interpolation = multi_config.get_interpolation_method_display()
        except MultiLadderCalibrationConfig.DoesNotExist:
            multi_ladder_enabled = False
            multi_ladder_template = None
            multi_ladder_interpolation = None

        # Build lane data
        lane_data_list = []
        for lane in lanes:
            lane_data = self._build_lane_data(lane)
            lane_data_list.append(lane_data)

        # Build calibration data
        calibration_data_list = []
        for calibration in calibrations:
            cal_data = self._build_calibration_data(calibration)
            calibration_data_list.append(cal_data)

        # Build report data
        report_data = ReportData(
            # Analysis metadata
            analysis_id=str(analysis.id),
            analysis_name=analysis.name or "Unnamed Analysis",
            analysis_status=analysis.get_status_display(),
            gel_type=analysis.gel_image.get_gel_type_display() if hasattr(analysis.gel_image, "gel_type") else "N/A",
            notes=analysis.notes,
            created_by_name=analysis.created_by.get_full_name() if analysis.created_by else "Unknown",
            created_at=analysis.created_at.strftime("%Y-%m-%d %H:%M") if analysis.created_at else "",
            # Image info
            image_title=analysis.gel_image.original_filename,
            image_width=analysis.gel_image.width,
            image_height=analysis.gel_image.height,
            gel_image_id=str(analysis.gel_image.id),
            # Lanes
            lanes=lane_data_list,
            # Calibrations
            calibrations=calibration_data_list,
            has_calibration=len(calibration_data_list) > 0,
            # Multi-ladder
            multi_ladder_enabled=multi_ladder_enabled,
            multi_ladder_template=multi_ladder_template,
            multi_ladder_interpolation=multi_ladder_interpolation,
            # Counts
            total_lanes_count=len(lane_data_list),
            total_bands_count=sum(len(lane.bands) for lane in lane_data_list),
            # Report metadata
            report_generated_at=timezone.now().strftime("%B %d, %Y at %H:%M"),
            report_generated_by=_user_display(user),
            software_version="GelAnalyzer v1.0",
        )

        logger.info(f"Collected data for {report_data.total_lanes_count} lanes, {report_data.total_bands_count} bands")

        return report_data

    def _build_lane_data(self, lane: Lane) -> LaneReportData:
        """
        Build LaneReportData from Lane model instance.

        Args:
            lane: Lane instance

        Returns:
            LaneReportData with bands and densitometry
        """
        # Get sample name
        # Phoresis has no ProcessSample registry — lanes always carry sample_name directly.
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
            lane_type_code=lane.lane_type or "SAMPLE",
            lane_shape=getattr(lane, "lane_shape", "RECTANGLE") or "RECTANGLE",
            sample_name=sample_name,
            condition=lane.condition_display,
            protein_load_ug=lane.protein_load_ug,
            protein_load_type=lane.get_protein_load_type_display() if lane.protein_load_type else "",
            notes=lane.notes,
            x=lane.x,
            y=lane.y,
            width=lane.width,
            height=lane.height,
            polygon=getattr(lane, "polygon", None) or None,
            bands=bands,
            total_integrated_area=total_area,
            poi_integrated_area=poi_area,
            poi_percentage=poi_pct,
            band_count=band_count,
            poi_band_count=poi_band_count,
            profile_data=profile_data,
        )

    def _build_band_data(self, band: Band) -> BandReportData:
        """
        Build BandReportData from Band model instance.

        Args:
            band: Band instance

        Returns:
            BandReportData with densitometry results
        """
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

    def _build_calibration_data(self, calibration: LadderCalibration) -> CalibrationReportData:
        """
        Build CalibrationReportData from LadderCalibration instance.

        Args:
            calibration: LadderCalibration instance

        Returns:
            CalibrationReportData
        """
        template_name = calibration.template.name if calibration.template else "Unknown"
        manufacturer = calibration.template.manufacturer if calibration.template else "Unknown"

        return CalibrationReportData(
            ladder_lane_number=calibration.ladder_lane.lane_number if calibration.ladder_lane else 0,
            template_name=template_name,
            manufacturer=manufacturer,
            method=calibration.get_method_display(),
            equation=calibration.equation_display,
            r_squared=calibration.r_squared,
            r_squared_quality=calibration.r_squared_quality,
            matched_band_count=calibration.matched_band_count,
            band_matches=calibration.band_matches,
        )
