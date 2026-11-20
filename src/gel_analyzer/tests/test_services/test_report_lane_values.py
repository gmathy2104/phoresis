"""
The reports print each lane, and each band, as the analysis page does (``services/report/page_rows.py``).

Until 2026-10-13 they printed the lane summary's raw POI share as "Purity" on every gel: 0.0 % on each
lane of an anti-HCP blot instead of its HCP signal in % of the reference lane, and 0.0 % on a lane with
no POI band, where the page says "no POI band"; a band drawn in the editor had no name ("-"), a saturated band no
warning, and a deck's lane slide dropped every band past the 8th. Read back from the files, as a reader opens them.
"""

import io

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    GelAnalysis,
    GelAssay,
    GelImage,
    Lane,
    LaneDensitometrySummary,
    SavedComparison,
    SavedComparisonLane,
)
from gel_analyzer.services.report.comparison_builder import ComparisonReportBuilder
from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector
from gel_analyzer.services.report.comparison_excel_builder import ComparisonExcelBuilder
from gel_analyzer.services.report.comparison_pptx_builder import ComparisonPowerPointBuilder
from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder
from gel_analyzer.services.report.densitometry_data_collector import DensitometryDataCollector
from gel_analyzer.services.report.densitometry_excel_builder import DensitometryExcelBuilder
from gel_analyzer.services.report.densitometry_pptx_builder import DensitometryPowerPointBuilder
from gel_analyzer.services.report.pptx_base import BasePptxReportBuilder

pytestmark = pytest.mark.django_db

WB = GelImage.GelType.WESTERN_BLOT
POI = Band.BandType.POI
OTHER = Band.BandType.OTHER


def _band(lane, y, band_type=OTHER):
    return Band.objects.create(
        lane=lane, band_type=band_type, position_y=y, bbox_x=lane.x, bbox_y=y - 5, bbox_width=lane.width, bbox_height=10
    )


def give_densitometry(lane, areas):
    """What a Run Analysis leaves on ``lane``: a DensitometryResult per band of ``areas``
    ({band: corrected area}), then the lane summary LAST -- a Band save wipes both."""
    for band, area in areas.items():
        DensitometryResult.objects.update_or_create(
            band=band,
            defaults={
                "peak_center_y": band.position_y,
                "peak_amplitude": 1.0,
                "peak_sigma": 1.0,
                "fwhm": 2.35,
                "integrated_area": area,
                "corrected_area": area,
                "fit_r_squared": 0.99,
                "snr": 10.0,
            },
        )
    LaneDensitometrySummary.objects.update_or_create(lane=lane, defaults={"total_integrated_area": sum(areas.values())})


@pytest.fixture
def hcp_blot(db):
    """An analysed anti-HCP western; no reference lane.

    L1 (S1): OTHER 100 + OTHER 100 + POI 5000, plus an OTHER band never integrated.
    L2 (S2): OTHER 50 + POI 9000. L3: analysed, no sample.
    """
    assay = GelAssay.objects.create(name="Test anti-HCP blot", gel_type=WB, readout=GelAssay.Readout.HOST_CELL_PROTEINS)
    image = GelImage.objects.create(
        original_file="wb.png", original_filename="WB anti-HCP.scn", gel_type=WB, assay=assay
    )
    analysis = GelAnalysis.objects.create(gel_image=image, name="HCP blot")
    s1, s2 = "S1", "S2"
    l1, l2, l3 = (
        Lane.objects.create(analysis=analysis, lane_number=n, x=50 * n, y=0, width=40, height=300, sample_name=s)
        for n, s in ((1, s1), (2, s2), (3, ""))
    )
    # Every band first: a Band save wipes its lane's densitometry.
    l1_bands = (_band(l1, 80), _band(l1, 120), _band(l1, 200, POI))
    _band(l1, 250)  # never integrated: no DensitometryResult, nothing to count
    l2_bands = (_band(l2, 80), _band(l2, 200, POI))
    l3_bands = (_band(l3, 80),)
    areas = {
        l1: dict(zip(l1_bands, (100.0, 100.0, 5000.0), strict=True)),
        l2: dict(zip(l2_bands, (50.0, 9000.0), strict=True)),
        l3: dict(zip(l3_bands, (70.0,), strict=True)),
    }
    for lane, lane_areas in areas.items():
        give_densitometry(lane, lane_areas)
    return {"analysis": analysis, "lanes": (l1, l2, l3), "samples": (s1, s2), "areas": areas}


def _set_reference(analysis, lane):
    analysis.readout_reference_lane = lane
    analysis.save(update_fields=["readout_reference_lane"])


def _slide_table(deck, title):
    """The rows (cell texts) of the table on the deck's slide titled ``title``."""
    for slide in Presentation(io.BytesIO(deck.getvalue())).slides:
        if slide.shapes.title is not None and slide.shapes.title.text == title:
            table = next(shape.table for shape in slide.shapes if shape.has_table)
            return [[cell.text for cell in row.cells] for row in table.rows]
    raise AssertionError(f"no slide titled {title!r}")


def _sheet_rows(workbook, name):
    """The rows (values) of the workbook's sheet ``name``."""
    sheet = load_workbook(io.BytesIO(workbook.getvalue()))[name]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def test_anti_hcp_report_prints_the_hcp_percent_of_reference_not_a_zero_purity(hcp_blot, test_user):
    """L1's HCP signal is its two OTHER bands (100 + 100; the POI band is left out), the reference L2's is 50:
    the page reads L1 at 400.0 % of the reference. The deck printed "Purity (%)" from the POI share. Each lane is
    the page's: its sample, the reference marked, a lane without a sample saying so."""
    analysis = hcp_blot["analysis"]
    _l1, l2, _l3 = hcp_blot["lanes"]
    s1, s2 = hcp_blot["samples"]
    _set_reference(analysis, l2)
    data = DensitometryDataCollector().collect(analysis, test_user)
    # Each band carries its part in the readout, as the page colours it: the key bands its gel slide draws.
    lane_1 = next(lane for lane in data.lanes if lane.lane_number == 1)
    assert sorted((b.band_type_code, b.role) for b in lane_1.bands if b.role) == [
        ("OTHER", "hcp"),
        ("OTHER", "hcp"),
        ("POI", "left_out"),
    ]

    header, *rows = _slide_table(
        DensitometryPowerPointBuilder(data, sections=["sample_summary"]).build(), "Sample Summary"
    )
    assert not [column for column in header if "Purity" in column]
    lane_1 = next(row for row in rows if row[0] == "1")
    assert lane_1[header.index("HCP % of ref.")] == "400.0 %"
    assert [row[header.index("Sample")] for row in rows] == [s1, f"{s2} (REF)", "no sample"]

    header, *rows = _sheet_rows(DensitometryExcelBuilder(data, sections=["sample_summary"]).build(), "Sample Summary")
    lane_1 = next(row for row in rows if row[0] == 1)
    assert lane_1[header.index("HCP % of ref.")] == pytest.approx(400.0)


def test_purity_report_says_no_poi_band_where_a_lane_has_no_poi_signal_never_zero(test_user):
    """An SDS-PAGE lane whose POI band carries no signal has no purity (``published_purity``): the page says
    "no POI band". The deck and the workbook printed the summary's 0.0."""
    image = GelImage.objects.create(
        original_file="sds.png", original_filename="SDS.png", gel_type=GelImage.GelType.SDS_PAGE
    )
    analysis = GelAnalysis.objects.create(gel_image=image, name="SDS gel")
    lane = Lane.objects.create(analysis=analysis, lane_number=1, x=50, y=0, width=40, height=300, sample_name="S1")
    other, poi = _band(lane, 80), _band(lane, 200, Band.BandType.POI)
    give_densitometry(lane, {other: 300.0, poi: 0.0})
    LaneDensitometrySummary.objects.filter(lane=lane).update(poi_integrated_area=0.0, poi_percentage=0.0)
    data = DensitometryDataCollector().collect(analysis, test_user)

    header, *rows = _slide_table(
        DensitometryPowerPointBuilder(data, sections=["sample_summary"]).build(), "Sample Summary"
    )
    purity = next(index for index, column in enumerate(header) if column.startswith("Purity"))
    assert rows[0][purity] == "no POI band"

    header, *rows = _sheet_rows(DensitometryExcelBuilder(data, sections=["sample_summary"]).build(), "Sample Summary")
    purity = next(index for index, column in enumerate(header) if column.startswith("Purity"))
    assert rows[0][purity] == "no POI band"


# Two bands more than a lane slide holds under its electropherogram (a band table in two columns): the table must
# continue on another slide.
LONG_LANE_BANDS = (
    2
    * BasePptxReportBuilder.rows_fitting(
        BasePptxReportBuilder.BAND_TABLE_TOP_IN, BasePptxReportBuilder.BAND_ROW_HEIGHT_IN
    )
    + 2
)


def _long_lane(test_user):
    """An SDS-PAGE lane of ``LONG_LANE_BANDS`` bands drawn in the editor (no stored number). The saturated one (5 % of
    its pixels clipped, above the default 1 % threshold) is created FIRST but sits LOWEST: named by its rank from the
    top, it is the last band, never B1. Beside it on the gel, a ladder (lane 2, markers of 250 and 10 kDa) and an
    empty lane (lane 3)."""
    image = GelImage.objects.create(
        original_file="sds.png", original_filename="SDS.png", gel_type=GelImage.GelType.SDS_PAGE
    )
    analysis = GelAnalysis.objects.create(gel_image=image, name="SDS gel")
    lowest = 20 + 30 * LONG_LANE_BANDS
    lane = Lane.objects.create(
        analysis=analysis, lane_number=1, x=50, y=0, width=40, height=lowest + 20, sample_name="S1"
    )
    saturated = _band(lane, lowest)
    bands = [saturated] + [
        _band(lane, 20 + 30 * i, Band.BandType.POI if i == 4 else Band.BandType.OTHER)
        for i in range(LONG_LANE_BANDS - 1)
    ]
    give_densitometry(lane, dict.fromkeys(bands, 100.0))
    # What a run stores: every band's share of clipped pixels (none here), the saturated one's 5 %.
    DensitometryResult.objects.filter(band__lane=lane).update(saturated_pixel_fraction=0.0)
    DensitometryResult.objects.filter(band=saturated).update(saturated_pixel_fraction=0.05)
    ladder = Lane.objects.create(
        analysis=analysis, lane_number=2, lane_type=Lane.LaneType.LADDER, x=150, y=0, width=40, height=lowest + 20
    )
    for y, kda in ((30, 250.0), (300, 10.0)):
        Band.objects.filter(pk=_band(ladder, y, Band.BandType.MW_REFERENCE).pk).update(estimated_mw_kda=kda)
    Lane.objects.create(
        analysis=analysis, lane_number=3, lane_type=Lane.LaneType.EMPTY, x=250, y=0, width=40, height=lowest + 20
    )
    return analysis, lane


def _band_rows(deck, lane_title):
    """The band table rows of a lane's slide and of its continuation slides -- each table, the left column first -- in
    the deck's order."""
    rows = []
    for slide in Presentation(io.BytesIO(deck.getvalue())).slides:
        title = slide.shapes.title.text if slide.shapes.title is not None else ""
        if title in (lane_title, f"{lane_title} — bands (continued)"):
            for shape in sorted((shape for shape in slide.shapes if shape.has_table), key=lambda shape: shape.left):
                header, *body = [[cell.text for cell in row.cells] for row in shape.table.rows]
                rows += [dict(zip(header, row, strict=False)) for row in body]
    return rows


def test_densitometry_report_names_every_band_as_the_page_flags_the_saturated_one_and_drops_none(test_user):
    """The deck's lane slide kept the first 8 bands, numbered "-" when drawn in the editor, and no report said a band
    was saturated; the workbook wrote a blank band number. The last band, saturated, was in no table at all."""
    analysis, _lane = _long_lane(test_user)
    data = DensitometryDataCollector().collect(analysis, test_user)
    last = f"B{LONG_LANE_BANDS}"

    # The gel's pictures carry the ladder's kDa (the sample identity card's ticks).
    assert [(tick["mw_kda"], tick["y"]) for tick in data.mw_ticks] == [(250.0, 30), (10.0, 300)]

    deck = DensitometryPowerPointBuilder(data, sections=["sample_summary", "lane_details"]).build()
    titles = [s.shapes.title.text for s in Presentation(io.BytesIO(deck.getvalue())).slides if s.shapes.title]
    assert not [title for title in titles if title.startswith(("Lane 2:", "Lane 3:"))]  # no ladder or empty lane slide
    rows = _band_rows(deck, "Lane 1: S1")
    assert [row["Band"] for row in rows] == [f"B{n}" for n in range(1, LONG_LANE_BANDS + 1)]
    assert [row["Saturation"] for row in rows] == [""] * (LONG_LANE_BANDS - 1) + ["⚠ 5.0 % clipped"]
    header, *summary = _slide_table(deck, "Sample Summary")
    assert summary[0][header.index("Saturated")] == f"⚠ {last} (Other)"

    header, *rows = _sheet_rows(DensitometryExcelBuilder(data, sections=["lane_details"]).build(), "Lane Details")
    rows = [dict(zip(header, row, strict=False)) for row in rows if row[header.index("Lane #")] == 1]
    assert [row["Band"] for row in rows] == [f"B{n}" for n in range(1, LONG_LANE_BANDS + 1)]
    assert [row["Saturated"] for row in rows] == ["No"] * (LONG_LANE_BANDS - 1) + ["Yes"]
    assert rows[-1]["Clipped pixels (%)"] == pytest.approx(5.0)


def test_comparison_deck_names_and_flags_the_bands_of_its_lanes_through_its_own_code(test_user):
    """The comparison report builds its band rows and its lane slides with code of its own: the same lane reads alike."""
    _analysis, lane = _long_lane(test_user)
    comparison = SavedComparison.objects.create(name="Comparison", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)
    data = ComparisonDataCollector().collect(comparison, test_user)

    rows = _band_rows(ComparisonPowerPointBuilder(data, sections=["lane_details"]).build(), "1 · L1 · S1")
    assert [row["Band"] for row in rows] == [f"B{n}" for n in range(1, LONG_LANE_BANDS + 1)]
    assert rows[-1]["Saturation"] == "⚠ 5.0 % clipped"


def _purity_lane(analysis, number, lane_type, purity):
    """A lane of ``analysis`` whose POI band holds ``purity`` % of its signal."""
    lane = Lane.objects.create(
        analysis=analysis,
        lane_number=number,
        lane_type=lane_type,
        x=50 * number,
        y=0,
        width=40,
        height=300,
        sample_name=f"S{number}",
    )
    poi, other = _band(lane, 100, Band.BandType.POI), _band(lane, 200)
    give_densitometry(lane, {poi: purity, other: 100.0 - purity})
    LaneDensitometrySummary.objects.filter(lane=lane).update(poi_integrated_area=purity, poi_percentage=purity)
    return lane


def test_comparison_report_reads_each_lane_by_its_assay_and_averages_the_purity_samples(hcp_blot, test_user):
    """An SDS-PAGE gel (two sample lanes at 80 % and 60 %, a control at 90 %) compared with an anti-HCP blot's lane 1
    (400.0 % of its reference lane 2). The comparison report printed one "Purity (%)" column for all of them -- the
    blot lane's POI share among them -- and no mean purity."""
    image = GelImage.objects.create(
        original_file="sds.png", original_filename="SDS.png", gel_type=GelImage.GelType.SDS_PAGE
    )
    sds = GelAnalysis.objects.create(gel_image=image, name="SDS gel")
    sample_80 = _purity_lane(sds, 1, Lane.LaneType.SAMPLE, 80.0)
    sample_60 = _purity_lane(sds, 2, Lane.LaneType.SAMPLE, 60.0)
    control_90 = _purity_lane(sds, 3, Lane.LaneType.CONTROL, 90.0)
    hcp_lane_1, hcp_lane_2, _l3 = hcp_blot["lanes"]
    _set_reference(hcp_blot["analysis"], hcp_lane_2)
    comparison = SavedComparison.objects.create(name="Comparison", created_by=test_user)
    for order, lane in enumerate((sample_80, sample_60, control_90, hcp_lane_1)):
        SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=order)
    data = ComparisonDataCollector().collect(comparison, test_user)
    blot_lane = next(lane for lane in data.lanes if lane.lane_id == hcp_lane_1.pk)
    assert sorted((b.band_type_code, b.role) for b in blot_lane.bands if b.role) == [
        ("OTHER", "hcp"),
        ("OTHER", "hcp"),
        ("POI", "left_out"),
    ]

    deck = ComparisonPowerPointBuilder(data, sections=["overview", "sample_summary"]).build()
    header, *rows = _slide_table(deck, "Sample Summary — SDS-PAGE")
    assert rows[0][header.index("Purity")] == "80.0 %"
    header, *rows = _slide_table(deck, "Sample Summary — Test anti-HCP blot")
    assert not [column for column in header if "Purity" in column]
    assert rows[0][header.index("HCP % of ref.")] == "400.0 %"
    overview = dict(row for row in _slide_table(deck, "Comparison Overview"))
    assert overview["Mean purity · SDS-PAGE"] == "70.0% (2 of 2 sample lanes)"  # the control is not averaged

    header, *rows = _sheet_rows(ComparisonExcelBuilder(data, sections=["sample_summary"]).build(), "Sample Summary")
    blot = dict(zip(header, rows[3], strict=False))
    assert blot["HCP % of ref."] == pytest.approx(400.0)
    assert blot["Purity"] is None

    # The Word report runs its own per-assay loop, and drops a section that raises without a word.
    tables = Document(
        io.BytesIO(ComparisonReportBuilder(data, sections=["overview", "sample_summary"]).build().getvalue())
    ).tables
    header, *rows = next(
        [[cell.text for cell in row.cells] for row in table.rows]
        for table in tables
        if "HCP % of ref." in [cell.text for cell in table.rows[0].cells]
    )
    assert not [column for column in header if "Purity" in column]
    assert rows[0][header.index("HCP % of ref.")] == "400.0 %"
    overview = {row.cells[0].text: row.cells[-1].text for table in tables for row in table.rows}
    assert overview["Mean purity · SDS-PAGE"] == "70.0% (2 of 2 sample lanes)"


def test_densitometry_report_opens_on_the_pages_checks_and_readout_card(test_user):
    """The overview was a key/value table: no word of a saturated band (or a lane without its POI band, or its sample),
    "Average Purity" whatever the gel measured, a blank Analyst for an account without a full name. It now prints the
    analysis page's "To check" items and its readout card, in the deck, the workbook and the Word report alike."""
    analysis, _lane = _long_lane(test_user)
    GelAnalysis.objects.filter(pk=analysis.pk).update(created_by=test_user)  # no full name: named by username
    data = DensitometryDataCollector().collect(GelAnalysis.objects.get(pk=analysis.pk), test_user)

    deck = Presentation(io.BytesIO(DensitometryPowerPointBuilder(data, sections=["overview"]).build().getvalue()))
    slide = next(s for s in deck.slides if s.shapes.title is not None and s.shapes.title.text == "Analysis Overview")
    frames = [shape.text_frame for shape in slide.shapes if shape.has_text_frame]
    paragraphs = [paragraph.text for frame in frames for paragraph in frame.paragraphs]
    assert "⚠ Lane 1: saturated band" in paragraphs
    assert "MEAN PURITY\n—\n0 of 1 sample lanes" in [frame.text for frame in frames]
    assert "Analyst  test_user" in paragraphs

    rows = _sheet_rows(DensitometryExcelBuilder(data, sections=["overview"]).build(), "Overview")
    assert ["Warning", "Lane 1: saturated band"] in [row[:2] for row in rows]
    assert "Mean purity" in [row[0] for row in rows]

    document = Document(io.BytesIO(DensitometryReportBuilder(data, sections=["overview"]).build().getvalue()))
    assert "⚠ Lane 1: saturated band" in [paragraph.text for paragraph in document.paragraphs]
    facts = {row.cells[0].text: row.cells[-1].text for table in document.tables for row in table.rows}
    assert facts["Mean purity"] == "— (0 of 1 sample lanes)"
