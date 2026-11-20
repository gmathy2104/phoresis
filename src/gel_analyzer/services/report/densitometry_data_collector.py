"""
Data collector for densitometry report generation.

Queries GelAnalysis and related models, returns structured dataclasses for report generation.
Reuses LaneReportData, BandReportData, CalibrationReportData from data_collector.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gel_analyzer.models import (
    GelAnalysis,
    GelAssay,
    LaneDensitometrySummary,
)
from gel_analyzer.services.mean_purity import mean_purity
from gel_analyzer.signals import published_purity
from phoresis_core.logging_config import get_logger

from .data_collector import (
    CalibrationReportData,
    LaneReportData,
    QuantCalibrationReportData,
    QuantControlReportData,
    QuantPointReportData,
    QuantSampleReportData,
    ReportDataCollector,
)
from .page_rows import apply_page_rows, gel_mw_ticks, lane_strips, sample_text

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

    # What the gel is read for and the columns of its lane values, as the analysis page shows them
    # (page_rows.apply_page_rows): every lane value of the reports is the page's cell.
    readout: str = ""
    readout_label: str = ""
    readout_columns: list = field(default_factory=list)
    # The page's summary (page_rows.PageReadout): its assay, header hint, metric cards and "To check" items.
    assay_label: str = ""
    status_hint: str = ""
    cards: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    # The gel's kDa ticks in image pixels (page_rows.gel_mw_ticks: the ladder's markers), for its pictures.
    mw_ticks: list = field(default_factory=list)
    # Each lane's sample identity card entry, by lane id (page_rows.lane_strips), for its lane slide's figure.
    strips: dict = field(default_factory=dict)

    # Densitometry aggregations: the gel's mean purity and the lanes it averages (services/mean_purity.py)
    average_purity: float | None = None
    average_purity_lanes: str = ""
    densitometry_computed_at: str | None = None

    # Report metadata
    report_generated_at: str = ""
    report_generated_by: str = ""
    software_version: str = "GelAnalyzer v1.0"

    # Protein quantification (read-only re-fit; populated by _collect_quantification)
    has_quantification: bool = False
    quant_calibration: QuantCalibrationReportData | None = None
    quant_points: list[QuantPointReportData] = field(default_factory=list)
    quant_controls: list[QuantControlReportData] = field(default_factory=list)
    quant_samples: list[QuantSampleReportData] = field(default_factory=list)

    @property
    def average_purity_text(self) -> str:
        """The reports' "Average Purity": the mean and the lanes it averages, "N/A" when there is none."""
        if self.average_purity is None:
            return "N/A"
        lanes = f" ({self.average_purity_lanes})" if self.average_purity_lanes else ""
        return f"{self.average_purity:.1f}%{lanes}"


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

        # Anti-HCP western: the reference lane's label says so in every report (spec §4.2). The
        # digital-gel header cuts labels at 14 characters, which may hide the suffix there: accepted.
        gel_image = getattr(analysis, "gel_image", None)
        assay = gel_image.assay if gel_image is not None and gel_image.assay_id is not None else None
        if (
            assay is not None
            and assay.readout == GelAssay.Readout.HOST_CELL_PROTEINS
            and analysis.readout_reference_lane_id is not None
        ):
            for lane_data in base_data.lanes:
                if lane_data.lane_id == analysis.readout_reference_lane_id:
                    lane_data.sample_name = f"{lane_data.sample_name} (reference)"

        # Each lane's values as the analysis page shows them.
        page = apply_page_rows(analysis, base_data.lanes)

        # Get gel image ID
        gel_image_id = None
        if hasattr(analysis, "gel_image") and analysis.gel_image:
            gel_image_id = analysis.gel_image.pk

        # The analysis page's mean purity: a report lane carries its summary's POI share, which
        # published_purity reads as it does the summary's.
        purity = mean_purity(gel_image, ((lane.lane_type_code, published_purity(lane)) for lane in base_data.lanes))
        average_purity = purity.value

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

        # Read-only protein quantification re-fit (never persists)
        lanes_by_id = {lane.lane_number: lane for lane in base_data.lanes}
        try:
            quant = self._collect_quantification(analysis, lanes_by_id)
        except Exception as e:
            logger.warning(f"Quantification collection failed: {e}")
            quant = {"has_quantification": False}

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
            # The page's readout
            readout=page.readout,
            readout_label=page.label,
            readout_columns=page.columns,
            assay_label=page.assay_label,
            status_hint=page.status_hint,
            cards=list(page.cards),
            checks=list(page.checks),
            mw_ticks=gel_mw_ticks(analysis.pk),
            strips=lane_strips(
                [lane.lane_id for lane in base_data.lanes if lane.lane_type_code not in ("LADDER", "EMPTY")]
            ),
            # Densitometry aggregations
            average_purity=average_purity,
            average_purity_lanes=purity.lanes_text,
            densitometry_computed_at=densitometry_computed_at,
            # Report metadata
            report_generated_at=base_data.report_generated_at,
            report_generated_by=base_data.report_generated_by,
            software_version=base_data.software_version,
            # Protein quantification
            has_quantification=quant.get("has_quantification", False),
            quant_calibration=quant.get("quant_calibration"),
            quant_points=quant.get("quant_points", []),
            quant_controls=quant.get("quant_controls", []),
            quant_samples=quant.get("quant_samples", []),
        )

        logger.info(
            f"Collected densitometry data: {report_data.total_lanes_count} lanes, "
            f"{report_data.total_bands_count} bands, avg purity={average_purity}"
        )

        return report_data

    @staticmethod
    def _r_squared_quality(r_squared) -> str:
        """Mirror gel_analyzer.views.analyses r_squared quality buckets."""
        if r_squared is None:
            return "unknown"
        if r_squared >= 0.99:
            return "excellent"
        if r_squared >= 0.95:
            return "good"
        if r_squared >= 0.90:
            return "acceptable"
        return "poor"

    def _collect_quantification(self, analysis, lanes_by_id):
        """Re-run the active ProteinQuantCalibration's fit + projections READ-ONLY.

        Mirrors api/views.py::_build_full_result but persists nothing
        (never calls save_active / apply_to_analysis). Returns a dict of the
        top-level quant fields, or {'has_quantification': False} when no active
        calibration exists.

        lanes_by_id maps lane_number -> LaneReportData (for sample_name lookup).
        """
        from gel_analyzer.models import ProteinQuantCalibration
        from gel_analyzer.services.quantification.models import QC_RECOVERY_RANGE, QuantParams
        from gel_analyzer.services.quantification.service import (
            ProteinQuantCalibrationService,
            calibration_area_span,
            calibration_range_of,
        )

        from .constants import unit_display

        calib = (
            ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True)
            .select_related("created_by")
            .first()
        )
        if calib is None:
            return {"has_quantification": False}

        unit_label = unit_display(calib.unit)
        calib_data = QuantCalibrationReportData(
            method=calib.get_method_display(),
            unit=unit_label,
            equation=calib.equation,
            r_squared=calib.r_squared,
            r_squared_quality=self._r_squared_quality(calib.r_squared),
            n_points=0,  # filled below from the successful fit
            n_excluded=len(calib.excluded_band_ids or []),
            created_by_name=(
                calib.created_by.get_full_name() or calib.created_by.username if calib.created_by else "Unknown"
            ),
            created_at=(calib.created_at.strftime("%Y-%m-%d %H:%M") if calib.created_at else ""),
            last_recomputed_at=(
                calib.last_recomputed_at.strftime("%Y-%m-%d %H:%M") if calib.last_recomputed_at else None
            ),
            notes=calib.notes or "",
        )

        result = {
            "has_quantification": True,
            "quant_calibration": calib_data,
            "quant_points": [],
            "quant_controls": [],
            "quant_samples": [],
        }

        try:
            svc = ProteinQuantCalibrationService(QuantParams(method=calib.method, unit=calib.unit))
            cal_points = svc.collect_calibration_points(analysis)
            fit = svc.fit(cal_points, excluded_band_ids=calib.excluded_band_ids or [])
            if not fit.success:
                logger.warning(f"Quant report re-fit failed for analysis {analysis.id}: {fit.error_message}")
                return result  # methodology only, no derived rows
        except Exception as e:  # never break the report
            logger.warning(f"Quant report re-fit raised for analysis {analysis.id}: {e}")
            return result

        # n_points = non-excluded calibration points
        calib_data.n_points = sum(1 for p in fit.calibration_points if not p.is_excluded)
        # The standards' areas each projection is read against (the rule apply_to_analysis stores).
        span = calibration_area_span(
            ((p.band_id, p.corrected_area) for p in fit.calibration_points), calib.excluded_band_ids
        )

        # Table A — calibration points (residual_pct from p.residual / load_amount)
        points = []
        for p in fit.calibration_points:
            residual_pct = None
            if p.residual is not None and p.load_amount:
                residual_pct = round((p.residual / p.load_amount) * 100, 2)
            points.append(
                QuantPointReportData(
                    lane_number=p.lane_number,
                    load_amount=p.load_amount,
                    load_unit=unit_display(p.load_unit),
                    corrected_area=p.corrected_area,
                    residual_pct=residual_pct,
                    is_excluded=p.is_excluded,
                )
            )
        result["quant_points"] = points

        # Table B — controls/QC (project then derive recovery + out_of_spec)
        lo, hi = QC_RECOVERY_RANGE
        controls = []
        for c in svc.collect_control_points(analysis):
            predicted = svc.project(c.corrected_area, fit) if c.corrected_area is not None else None
            recovery_pct = None
            out_of_spec = False
            if predicted is not None and c.load_amount:
                recovery = (predicted / c.load_amount) * 100
                recovery_pct = round(recovery, 2)
                out_of_spec = not (lo <= recovery <= hi)
            controls.append(
                QuantControlReportData(
                    lane_number=c.lane_number,
                    known_amount=c.load_amount,
                    predicted_amount=(round(predicted, 4) if predicted is not None else None),
                    recovery_pct=recovery_pct,
                    out_of_spec=out_of_spec,
                    calibration_range=calibration_range_of(c.corrected_area, span),
                )
            )
        result["quant_controls"] = controls

        # Table C — sample estimated amounts (read the band's OWN persisted estimated_amount
        # and range; fall back to a read-only projection if not back-filled yet).
        samples = []
        for s in svc.collect_sample_bands(analysis):
            estimated = None
            calibration_range = None
            unit_for_row = unit_label
            ld = lanes_by_id.get(s.lane_number)
            sample_name = sample_text(ld) if ld else ""  # the page's sample (page_rows), as every table prints it
            # A lane may hold several projected bands: match this row's band, never the lane's first estimate.
            stored = next((b for b in ld.bands if b.band_id == s.band_id), None) if ld is not None else None
            if stored is not None and stored.estimated_amount is not None:
                estimated = stored.estimated_amount
                unit_for_row = unit_display(stored.estimated_amount_unit) or unit_label
                calibration_range = stored.estimated_amount_range
            elif s.corrected_area is not None:
                projected = svc.project(s.corrected_area, fit)
                estimated = round(projected, 4) if projected is not None else None
            if calibration_range is None and estimated is not None:
                calibration_range = calibration_range_of(s.corrected_area, span)
            samples.append(
                QuantSampleReportData(
                    lane_number=s.lane_number,
                    sample_name=sample_name,
                    estimated_amount=estimated,
                    unit=unit_for_row,
                    calibration_range=calibration_range,
                )
            )
        result["quant_samples"] = samples

        return result
