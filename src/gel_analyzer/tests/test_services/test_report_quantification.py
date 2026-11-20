"""Phase 2 — Quantification report section tests (collectors + builders).

All tests are read-only over the active ProteinQuantCalibration; the collector
must NEVER call save_active/apply_to_analysis.
"""

import pytest

from gel_analyzer.models import Band, DensitometryResult, Lane, ProteinQuantCalibration
from gel_analyzer.services.report.data_collector import (
    BandReportData,
    QuantCalibrationReportData,
    QuantControlReportData,
    QuantPointReportData,
    QuantSampleReportData,
    ReportData,
    ReportDataCollector,
)

pytestmark = pytest.mark.django_db


def test_band_report_data_has_estimated_amount_fields():
    b = BandReportData(
        band_id="x",
        band_type="Protein of Interest",
        band_type_code="POI",
        band_number=1,
        position_y=100,
        estimated_mw_kda=55.0,
        label="POI",
    )
    assert b.estimated_amount is None
    assert b.estimated_amount_unit == ""


def test_quant_dataclasses_construct_with_expected_fields():
    calib = QuantCalibrationReportData(
        method="Linear",
        unit="µg",
        equation="y = 0.001x",
        r_squared=0.99,
        r_squared_quality="excellent",
        n_points=3,
        n_excluded=0,
        created_by_name="Tester",
        created_at="2026-06-03 10:00",
        last_recomputed_at=None,
        notes="",
    )
    assert calib.r_squared_quality == "excellent"
    pt = QuantPointReportData(
        lane_number=10,
        load_amount=5.0,
        load_unit="µg",
        corrected_area=5000.0,
        residual_pct=0.0,
        is_excluded=False,
    )
    assert pt.lane_number == 10
    ctrl = QuantControlReportData(
        lane_number=4,
        known_amount=10.0,
        predicted_amount=11.0,
        recovery_pct=110.0,
        out_of_spec=False,
    )
    assert ctrl.out_of_spec is False
    sample = QuantSampleReportData(
        lane_number=2,
        sample_name="Sample 1",
        estimated_amount=8.3,
        unit="µg",
    )
    assert sample.estimated_amount == 8.3


def test_report_data_has_quant_top_level_fields():
    rd = ReportData(
        analysis_id="a",
        analysis_name="n",
        analysis_status="Draft",
        gel_type="SDS-PAGE",
        notes="",
        created_by_name="t",
        created_at="",
        image_title="img",
        image_width=10,
        image_height=10,
    )
    assert rd.has_quantification is False
    assert rd.quant_calibration is None
    assert rd.quant_points == []
    assert rd.quant_controls == []
    assert rd.quant_samples == []


def test_base_collector_reads_estimated_amount(gel_analysis, test_user):
    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
        sample_name="S1",
    )
    band = Band.objects.create(
        lane=lane,
        band_type=Band.BandType.POI,
        position_y=100,
        detection_source=Band.DetectionSource.MANUAL,
        created_by=test_user,
    )
    DensitometryResult.objects.create(
        band=band,
        peak_center_y=100,
        peak_amplitude=50,
        peak_sigma=5,
        fwhm=11.77,
        integrated_area=1000,
        corrected_area=1000,
        fit_r_squared=0.99,
        snr=20,
        estimated_amount=7.5,
        estimated_amount_unit="UG",
    )
    data = ReportDataCollector().collect(gel_analysis, test_user)
    poi = data.lanes[0].bands[0]
    assert poi.estimated_amount == 7.5
    assert poi.estimated_amount_unit == "UG"


def test_comparison_collector_sets_type_codes_and_estimated_amount(gel_analysis, test_user):
    from gel_analyzer.models import SavedComparison, SavedComparisonLane
    from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector

    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
        sample_name="S1",
    )
    band = Band.objects.create(
        lane=lane,
        band_type=Band.BandType.POI,
        position_y=100,
        detection_source=Band.DetectionSource.MANUAL,
        created_by=test_user,
    )
    DensitometryResult.objects.create(
        band=band,
        peak_center_y=100,
        peak_amplitude=50,
        peak_sigma=5,
        fwhm=11.77,
        integrated_area=1000,
        corrected_area=1000,
        fit_r_squared=0.99,
        snr=20,
        estimated_amount=9.1,
        estimated_amount_unit="UG",
    )
    comparison = SavedComparison.objects.create(name="Cmp", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)

    data = ComparisonDataCollector().collect(comparison, test_user)
    cl = data.lanes[0]
    assert cl.lane_type_code == "SAMPLE"
    b = cl.bands[0]
    assert b.band_type_code == "POI"
    assert b.estimated_amount == 9.1
    assert b.estimated_amount_unit == "UG"


def test_quantification_section_registered_in_both_lists():
    from gel_analyzer.services.report.constants import (
        ALL_SECTION_KEYS,
        DENSITOMETRY_ALL_SECTION_KEYS,
        METHODOLOGY_QUANTIFICATION,
        unit_display,
    )

    assert "quantification" in ALL_SECTION_KEYS
    assert "quantification" in DENSITOMETRY_ALL_SECTION_KEYS
    assert "calibration" in METHODOLOGY_QUANTIFICATION.lower()
    assert unit_display("UG") == "µg"
    assert unit_display("UG_ML") == "µg/mL"
    assert unit_display("") == ""
    assert unit_display(None) == ""


# ---------------------------------------------------------------------------
# Task 4 — Densitometry collector read-only quant re-fit
# ---------------------------------------------------------------------------


def _make_active_calibration(
    analysis, user, *, method="LINEAR", unit="UG", excluded=None, r2=0.999, equation="y = 0.001x"
):
    from gel_analyzer.services.quantification.models import QuantParams
    from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

    svc = ProteinQuantCalibrationService(QuantParams(method=method, unit=unit))
    cal_points = svc.collect_calibration_points(analysis)
    result = svc.fit(cal_points, excluded_band_ids=excluded or [])
    assert result.success, result.error_message
    return ProteinQuantCalibration.objects.create(
        analysis=analysis,
        method=method,
        unit=unit,
        coefficients=result.coefficients,
        r_squared=result.r_squared,
        equation=result.equation,
        excluded_band_ids=excluded or [],
        is_active=True,
        created_by=user,
        notes="",
    )


def test_densito_collector_no_quant_when_no_active_calibration(three_calib_points_analysis, test_user):
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    data = DensitometryDataCollector().collect(three_calib_points_analysis, test_user)
    assert data.has_quantification is False
    assert data.quant_calibration is None


def test_densito_collector_builds_quant_section(three_calib_points_analysis, test_user):
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    _make_active_calibration(three_calib_points_analysis, test_user)
    data = DensitometryDataCollector().collect(three_calib_points_analysis, test_user)

    assert data.has_quantification is True
    assert data.quant_calibration is not None
    assert data.quant_calibration.method == "Linear"
    assert data.quant_calibration.unit == "µg"
    assert data.quant_calibration.n_points == 3
    assert data.quant_calibration.n_excluded == 0
    assert data.quant_calibration.r_squared_quality == "excellent"
    # Three calibration points (loads 5/10/15)
    assert len(data.quant_points) == 3
    assert {p.load_amount for p in data.quant_points} == {5.0, 10.0, 15.0}
    # residual_pct derived (near-zero for an ideal linear fit)
    for p in data.quant_points:
        assert p.residual_pct is not None
        assert abs(p.residual_pct) < 1.0


def test_densito_collector_quant_is_read_only(three_calib_points_analysis, test_user, django_assert_num_queries):
    """The collector must not create/update any ProteinQuantCalibration or
    DensitometryResult rows (no save_active / apply_to_analysis)."""
    from gel_analyzer.models import DensitometryResult
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    _make_active_calibration(three_calib_points_analysis, test_user)
    calib_count = ProteinQuantCalibration.objects.count()
    # No estimated_amount has been persisted (apply_to_analysis never called)
    pre_estimated = list(DensitometryResult.objects.values_list("estimated_amount", flat=True))

    DensitometryDataCollector().collect(three_calib_points_analysis, test_user)

    assert ProteinQuantCalibration.objects.count() == calib_count
    post_estimated = list(DensitometryResult.objects.values_list("estimated_amount", flat=True))
    assert pre_estimated == post_estimated  # unchanged → no writes


def test_densito_collector_quant_controls_recovery(gel_analysis, test_user):
    """A CONTROL lane band with a known load is projected and recovery derived."""
    from gel_analyzer.models import ProteinQuantCalibrationPoint
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    # 3 calibration points (loads 5/10/15, areas 5000/10000/15000)
    for i, (load, area) in enumerate([(5.0, 5000.0), (10.0, 10000.0), (15.0, 15000.0)]):
        lane = Lane.objects.create(
            analysis=gel_analysis,
            lane_number=20 + i,
            lane_type=Lane.LaneType.CALIBRATION,
            detection_source=Lane.DetectionSource.MANUAL,
            x=10 + i * 50,
            y=10,
            width=40,
            height=400,
        )
        band = Band.objects.create(
            lane=lane,
            band_type=Band.BandType.CALIBRATION,
            position_y=100,
            detection_source=Band.DetectionSource.MANUAL,
            created_by=test_user,
        )
        DensitometryResult.objects.create(
            band=band,
            peak_center_y=100,
            peak_amplitude=50,
            peak_sigma=5,
            fwhm=11.77,
            integrated_area=area,
            corrected_area=area,
            fit_r_squared=0.99,
            snr=20,
        )
        ProteinQuantCalibrationPoint.objects.create(band=band, load_amount=load, load_unit="UG", role="CALIBRATION")
    # Control lane: known load 10 µg, area 10000 → recovery ~100%
    ctrl_lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=30,
        lane_type=Lane.LaneType.CONTROL,
        detection_source=Lane.DetectionSource.MANUAL,
        x=300,
        y=10,
        width=40,
        height=400,
    )
    ctrl_band = Band.objects.create(
        lane=ctrl_lane,
        band_type=Band.BandType.CALIBRATION,
        position_y=100,
        detection_source=Band.DetectionSource.MANUAL,
        created_by=test_user,
    )
    DensitometryResult.objects.create(
        band=ctrl_band,
        peak_center_y=100,
        peak_amplitude=50,
        peak_sigma=5,
        fwhm=11.77,
        integrated_area=10000.0,
        corrected_area=10000.0,
        fit_r_squared=0.99,
        snr=20,
    )
    ProteinQuantCalibrationPoint.objects.create(band=ctrl_band, load_amount=10.0, load_unit="UG", role="CONTROL")
    _make_active_calibration(gel_analysis, test_user)

    data = DensitometryDataCollector().collect(gel_analysis, test_user)
    assert len(data.quant_controls) == 1
    c = data.quant_controls[0]
    assert c.known_amount == 10.0
    assert c.recovery_pct is not None
    assert 95.0 <= c.recovery_pct <= 105.0
    assert c.out_of_spec is False


def test_densito_collector_quant_fit_failure_returns_methodology_no_crash(gel_analysis, test_user):
    """If the read-only re-fit fails (e.g. <2 usable points) the collector still
    returns has_quantification True with a calibration block and empty points."""
    from gel_analyzer.models import ProteinQuantCalibrationPoint
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    # One calibration point WITHOUT densitometry → fit() fails (missing area)
    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=40,
        lane_type=Lane.LaneType.CALIBRATION,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
    )
    band = Band.objects.create(
        lane=lane,
        band_type=Band.BandType.CALIBRATION,
        position_y=100,
        detection_source=Band.DetectionSource.MANUAL,
        created_by=test_user,
    )
    ProteinQuantCalibrationPoint.objects.create(band=band, load_amount=10.0, load_unit="UG", role="CALIBRATION")
    ProteinQuantCalibration.objects.create(
        analysis=gel_analysis,
        method="LINEAR",
        unit="UG",
        coefficients={},
        r_squared=0.0,
        equation="",
        excluded_band_ids=[],
        is_active=True,
        created_by=test_user,
        notes="",
    )

    data = DensitometryDataCollector().collect(gel_analysis, test_user)
    assert data.has_quantification is True
    assert data.quant_calibration is not None  # methodology still present
    assert data.quant_points == []  # fit failed → no derived points


def test_comparison_collector_per_analysis_quant_summary(gel_analysis, test_user):
    from gel_analyzer.models import ProteinQuantCalibration, SavedComparison, SavedComparisonLane
    from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector

    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
        sample_name="S1",
    )
    ProteinQuantCalibration.objects.create(
        analysis=gel_analysis,
        method="LINEAR",
        unit="UG",
        coefficients={"slope": 0.001, "intercept": 0.0},
        r_squared=0.987,
        equation="y = 0.001x",
        excluded_band_ids=[],
        is_active=True,
        created_by=test_user,
        notes="",
    )
    comparison = SavedComparison.objects.create(name="Cmp", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)

    data = ComparisonDataCollector().collect(comparison, test_user)
    assert data.has_quantification is True
    summary = data.analysis_quant_summaries[str(gel_analysis.id)]
    assert summary["method"] == "Linear"
    assert summary["unit"] == "µg"
    assert summary["equation"] == "y = 0.001x"
    assert summary["r_squared"] == 0.987
    assert summary["r_squared_quality"] == "good"


def test_comparison_collector_no_quant_summary_when_none(gel_analysis, test_user):
    from gel_analyzer.models import SavedComparison, SavedComparisonLane
    from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector

    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
        sample_name="S1",
    )
    comparison = SavedComparison.objects.create(name="Cmp", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)

    data = ComparisonDataCollector().collect(comparison, test_user)
    assert data.has_quantification is False
    assert data.analysis_quant_summaries == {}


# ---------------------------------------------------------------------------
# Task 6 — Densitometry Word builder: quantification section
# ---------------------------------------------------------------------------


def _collect_densito(analysis, user):
    from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector

    return DensitometryDataCollector().collect(analysis, user)


def test_report_sample_table_lists_each_bands_own_estimate_not_the_lanes_first(quant_sample_lane, test_user):
    """A lane with several projected bands: Table C showed the lane's FIRST stored estimate on every row (the collector
    took the first band of the lane carrying one). Each row now reads its own band's estimate, with its range."""
    from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

    analysis, _bands = quant_sample_lane
    calibration = _make_active_calibration(analysis, test_user)  # the three standards: span 5000 - 15000
    ProteinQuantCalibrationService().apply_to_analysis(calibration)

    data = _collect_densito(analysis, test_user)
    rows = sorted((round(s.estimated_amount, 3), s.calibration_range) for s in data.quant_samples)
    assert rows == [(4.0, "BELOW_RANGE"), (10.0, "IN_RANGE"), (12.0, "IN_RANGE")]


def test_word_builder_quant_section_renders(three_calib_points_analysis, test_user):
    from docx import Document

    from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder

    _make_active_calibration(three_calib_points_analysis, test_user)
    data = _collect_densito(three_calib_points_analysis, test_user)
    buf = DensitometryReportBuilder(data, sections=["quantification"]).build()

    doc = Document(buf)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Protein Quantification" in text
    # methodology mentions calibration
    assert "calibration" in text.lower()
    # at least one table was emitted (Table A points)
    assert len(doc.tables) >= 1


def test_word_builder_no_quant_section_when_absent(complete_analysis, test_user):
    from docx import Document

    from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder

    data = _collect_densito(complete_analysis, test_user)
    assert data.has_quantification is False
    buf = DensitometryReportBuilder(data, sections=["quantification"]).build()
    doc = Document(buf)
    text = "\n".join(p.text for p in doc.paragraphs)
    # Section heading still numbers, but no calibration table content
    assert "fit unavailable" not in text  # no active calibration -> graceful skip


# ---------------------------------------------------------------------------
# Task 7 — Densitometry Excel builder: quantification tables (no curve)
# ---------------------------------------------------------------------------


def test_excel_builder_quant_sheet_renders(three_calib_points_analysis, test_user):
    from openpyxl import load_workbook

    from gel_analyzer.services.report.densitometry_excel_builder import DensitometryExcelBuilder

    _make_active_calibration(three_calib_points_analysis, test_user)
    data = _collect_densito(three_calib_points_analysis, test_user)
    buf = DensitometryExcelBuilder(data, sections=["quantification"]).build()

    wb = load_workbook(buf)
    assert "Quantification" in wb.sheetnames
    ws = wb["Quantification"]
    # Methodology + Table A header present somewhere in column A
    col_a = [str(c.value) for c in ws["A"] if c.value is not None]
    assert any("Lane" in v for v in col_a) or any("Method" in v for v in col_a)


def test_excel_builder_quant_not_skipped():
    from gel_analyzer.services.report.densitometry_excel_builder import _EXCEL_SKIP_SECTIONS

    assert "quantification" not in _EXCEL_SKIP_SECTIONS


# ---------------------------------------------------------------------------
# Task 8 — Densitometry PPTX builder: native XY_SCATTER curve + tables
# ---------------------------------------------------------------------------


def test_pptx_builder_quant_slides_render(three_calib_points_analysis, test_user):
    from pptx import Presentation

    from gel_analyzer.services.report.densitometry_pptx_builder import DensitometryPowerPointBuilder

    _make_active_calibration(three_calib_points_analysis, test_user)
    data = _collect_densito(three_calib_points_analysis, test_user)
    buf = DensitometryPowerPointBuilder(data, sections=["quantification"]).build()

    prs = Presentation(buf)
    # At least one slide produced (title + quant slides)
    assert len(prs.slides) >= 2
    # A native chart exists on some slide (the XY_SCATTER curve)
    has_chart = any(shape.has_chart for slide in prs.slides for shape in slide.shapes if hasattr(shape, "has_chart"))
    assert has_chart
    # A table exists too (Table A)
    has_table = any(shape.has_table for slide in prs.slides for shape in slide.shapes if hasattr(shape, "has_table"))
    assert has_table


def test_pptx_builder_no_crash_without_quant(complete_analysis, test_user):
    from pptx import Presentation

    from gel_analyzer.services.report.densitometry_pptx_builder import DensitometryPowerPointBuilder

    data = _collect_densito(complete_analysis, test_user)
    buf = DensitometryPowerPointBuilder(data, sections=["quantification"]).build()
    prs = Presentation(buf)  # must open without exception
    assert len(prs.slides) >= 1


# ---------------------------------------------------------------------------
# Task 9 — Comparison builders: per-analysis quant summary (Word/Excel/PPTX)
# ---------------------------------------------------------------------------


def _comparison_with_quant(gel_analysis, test_user):
    from gel_analyzer.models import ProteinQuantCalibration, SavedComparison, SavedComparisonLane

    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=40,
        height=400,
        sample_name="S1",
    )
    ProteinQuantCalibration.objects.create(
        analysis=gel_analysis,
        method="LINEAR",
        unit="UG",
        coefficients={"slope": 0.001, "intercept": 0.0},
        r_squared=0.987,
        equation="y = 0.001x",
        excluded_band_ids=[],
        is_active=True,
        created_by=test_user,
        notes="",
    )
    comparison = SavedComparison.objects.create(name="Cmp", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)
    from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector

    return ComparisonDataCollector().collect(comparison, test_user)


def test_comparison_word_quant_summary(gel_analysis, test_user):
    from docx import Document

    from gel_analyzer.services.report.comparison_builder import ComparisonReportBuilder

    data = _comparison_with_quant(gel_analysis, test_user)
    buf = ComparisonReportBuilder(data, sections=["quantification"]).build()
    doc = Document(buf)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Quantification" in text
    # equation surfaced (paragraph text or any table cell)
    assert "0.001x" in text or any("0.001x" in c.text for t in doc.tables for r in t.rows for c in r.cells)


def test_comparison_excel_quant_sheet(gel_analysis, test_user):
    from openpyxl import load_workbook

    from gel_analyzer.services.report.comparison_excel_builder import _EXCEL_SKIP_SECTIONS, ComparisonExcelBuilder

    assert "quantification" not in _EXCEL_SKIP_SECTIONS
    data = _comparison_with_quant(gel_analysis, test_user)
    buf = ComparisonExcelBuilder(data, sections=["quantification"]).build()
    wb = load_workbook(buf)
    assert "Quantification" in wb.sheetnames


def test_comparison_pptx_quant_slide(gel_analysis, test_user):
    from pptx import Presentation

    from gel_analyzer.services.report.comparison_pptx_builder import ComparisonPowerPointBuilder

    data = _comparison_with_quant(gel_analysis, test_user)
    buf = ComparisonPowerPointBuilder(data, sections=["quantification"]).build()
    prs = Presentation(buf)
    has_table = any(shape.has_table for slide in prs.slides for shape in slide.shapes if hasattr(shape, "has_table"))
    assert has_table


# ---------------------------------------------------------------------------
# Task 10 — end-to-end section validation
# ---------------------------------------------------------------------------


def test_quantification_key_accepted_by_section_validators():
    from gel_analyzer.services.report.constants import ALL_SECTION_KEYS, DENSITOMETRY_ALL_SECTION_KEYS

    # gel_analyzer/views/report_api.py validates submitted sections against these
    # lists; the key must be present so a {"sections": ["quantification"]} request
    # is not rejected.
    assert "quantification" in ALL_SECTION_KEYS
    assert "quantification" in DENSITOMETRY_ALL_SECTION_KEYS
