# gel_analyzer/tests/test_services/test_pptx_base.py
"""BasePptxReportBuilder on the neutral 16:9 deck (python-pptx's default template, widened in code)."""

from io import BytesIO

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.util import Emu, Inches

from gel_analyzer.services.report import pptx_base
from gel_analyzer.services.report.pptx_base import (
    CHART_BOX,
    IMAGE_WIDE_PICTURE_BOX,
    IMAGE_WIDE_TEXT_BOX,
    LAYOUTS,
    TITLE_BOX,
    BasePptxReportBuilder,
    new_wide_presentation,
)


def _png_bytes(w=200, h=100, color=(80, 120, 200)):
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _box(shape):
    return tuple(round(Emu(value).inches, 2) for value in (shape.left, shape.top, shape.width, shape.height))


def test_deck_is_an_empty_16_9_deck_built_without_a_template_file():
    prs = new_wide_presentation()
    assert len(prs.slides._sldIdLst) == 0
    assert len(prs.slide_masters) == 1
    assert (round(Emu(prs.slide_width).inches, 2), round(Emu(prs.slide_height).inches, 2)) == (13.33, 7.5)
    # No template path, no brand: the module opens no file of its own.
    assert not hasattr(pptx_base, "TEMPLATE_PATH")


def test_layouts_map_names_layouts_of_the_default_template():
    names = {layout.name for layout in new_wide_presentation().slide_layouts}
    assert set(LAYOUTS) == {
        "cover",
        "section",
        "title_text",
        "title_chart",
        "image_text",
        "image_wide",
        "blank",
        "closing",
    }
    for key, name in LAYOUTS.items():
        assert name in names, f"{key}->{name!r} is not a layout of the default template"


def test_no_placeholder_runs_off_the_wide_slide_and_the_title_spans_it():
    """The default template is 10 in wide: every placeholder is rescaled, and a content slide's title and body span
    the 13.33 in slide."""
    prs = new_wide_presentation()
    for holder in [prs.slide_master, *prs.slide_layouts]:
        for ph in holder.placeholders:
            assert ph.left >= 0 and ph.left + ph.width <= prs.slide_width, (holder.name, ph.name)
    b = BasePptxReportBuilder()
    slide = b.new_slide("title_text")
    title = slide.shapes.title
    assert _box(title) == TITLE_BOX
    body = next(ph for ph in slide.placeholders if ph.placeholder_format.type == PP_PLACEHOLDER.OBJECT)
    assert round(Emu(body.width).inches, 2) == 12.33
    cover = b.new_slide("cover")
    assert round(Emu(cover.shapes.title.width).inches, 2) == 11.33


def test_section_divider_sets_its_title_and_its_subtitle():
    b = BasePptxReportBuilder()
    slide = b.add_section_divider("Results", "Lane by lane")
    assert slide.shapes.title.text == "Results"
    assert "Lane by lane" in [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
    assert slide.shapes.title.top < next(sh for sh in slide.shapes if sh.text_frame.text == "Lane by lane").top


def test_figure_slide_places_the_legend_left_and_the_picture_in_its_box():
    b = BasePptxReportBuilder()
    slide = b.add_figure_slide("Gel image — all bands", _png_bytes(826, 524), ["Lane outlines: blue sample", "Bands"])
    assert slide.shapes.title.text == "Gel image — all bands"
    picture = next(sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert _box(picture) == IMAGE_WIDE_PICTURE_BOX  # the box's own aspect: the picture fills it
    legend = next(sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.startswith("Lane outlines"))
    assert _box(legend)[:3] == IMAGE_WIDE_TEXT_BOX[:3]
    assert legend.left + legend.width <= picture.left
    # Without a picture: a visible placeholder, never a silent gap.
    empty = b.add_figure_slide("Gel image", None, [], placeholder_label="Gel image")
    assert "[ Gel image could not be rendered ]" in [sh.text_frame.text for sh in empty.shapes if sh.has_text_frame]


def test_tables_take_the_apps_accent_not_a_corporate_colour():
    b = BasePptxReportBuilder()
    assert b.TABLE_RULE == "2563EB"  # tokens.css --color-accent-600
    slide = b.new_slide("title_text")
    b._add_data_table(slide, ["Lane", "Area"], [["1", "100"]])
    xml = next(sh for sh in slide.shapes if sh.has_table)._element.xml
    assert 'val="2563EB"' in xml


def test_build_numbers_every_slide_but_the_cover_once():
    b = BasePptxReportBuilder()
    b.set_title(b.new_slide("cover"), "Report")
    b._add_header_bar(b._new_slide(), "Overview")
    b.build()
    deck = Presentation(b.build())  # a second build adds no second number
    numbers = [[sh.text_frame.text for sh in slide.shapes if sh.name == "Slide number"] for slide in deck.slides]
    assert numbers == [[], ["2"]]


def test_base_builder_starts_empty():
    b = BasePptxReportBuilder()
    assert len(b.prs.slides._sldIdLst) == 0
    assert b.warnings == []


def test_new_slide_for_each_layout_key():
    b = BasePptxReportBuilder()
    for key in LAYOUTS:
        slide = b.new_slide(key)
        assert slide is not None
    assert len(b.prs.slides._sldIdLst) == len(LAYOUTS)


def test_set_title_and_subtitle_on_cover():
    b = BasePptxReportBuilder()
    slide = b.new_slide("cover")
    b.set_title(slide, "Gel Report")
    b.set_subtitle(slide, "Densitometry")
    texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
    assert any("Gel Report" in t for t in texts)
    assert any("Densitometry" in t for t in texts)


def test_add_table_clears_default_style_and_paginates():
    b = BasePptxReportBuilder()
    slide = b.new_slide("title_text")
    rows = [["Lane", "Area"]] + [[str(i), f"{i * 100}"] for i in range(1, 21)]
    gf = b.add_table(
        slide,
        len(rows),
        2,
        col_widths=[2.0, 2.0],
        numeric_cols=(1,),
        max_rows=10,
        overflow_note="+{n} more",
    )
    table = gf.table
    # Header(1) + max_rows(10) body rows + 1 overflow row = 12
    assert len(table.rows) == 12
    # Default tableStyleId stamped by add_table must be cleared.
    tblPr = table._tbl.tblPr
    assert tblPr is None or tblPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId") is None
    # Overflow note present somewhere.
    cell_texts = [c.text for r in table.rows for c in r.cells]
    assert any("more" in t for t in cell_texts)


def test_numeric_cells_are_right_aligned():
    from pptx.enum.text import PP_ALIGN

    b = BasePptxReportBuilder()
    slide = b.new_slide("title_text")
    gf = b.add_table(slide, 3, 2, numeric_cols=(1,))
    table = gf.table
    # data-row numeric cell (row 1, col 1) right-aligned
    para = table.cell(1, 1).text_frame.paragraphs[0]
    assert para.alignment == PP_ALIGN.RIGHT


def test_add_picture_fit_locks_aspect():
    b = BasePptxReportBuilder()
    slide = b.new_slide("image_text")
    pic = b.add_picture_fit(
        slide,
        _png_bytes(200, 100),
        left=1.0,
        top=1.5,
        max_width=4.0,
        max_height=4.0,
    )
    # 200x100 (2:1) into a 4x4 box -> width 4", height 2" (aspect locked)
    from pptx.util import Inches

    assert abs(pic.width - Inches(4.0)) < Inches(0.05)
    assert abs(pic.height - Inches(2.0)) < Inches(0.05)


def test_add_speaker_notes_guards_none():
    b = BasePptxReportBuilder()
    slide = b.new_slide("title_text")
    b.add_speaker_notes(slide, "Reviewer notes here")
    assert "Reviewer notes here" in slide.notes_slide.notes_text_frame.text


def test_add_xy_scatter_inserts_native_chart():
    from pptx.enum.chart import XL_CHART_TYPE

    b = BasePptxReportBuilder()
    slide = b.new_slide("title_chart")
    chart = b.add_xy_scatter(
        slide,
        series=[
            ("Calibration", [(5.0, 5000.0), (10.0, 10000.0), (15.0, 15000.0)]),
            ("Fit", [(5.0, 5100.0), (15.0, 14900.0)]),
        ],
        x_title="Load (µg)",
        y_title="Corrected area",
    )
    assert chart is not None
    assert chart.chart_type == XL_CHART_TYPE.XY_SCATTER
    # The default template has no chart placeholder: the chart is a shape under the title, at CHART_BOX.
    frame = next(sh for sh in slide.shapes if sh.has_chart)
    assert _box(frame) == CHART_BOX
    assert frame.top >= slide.shapes.title.top + slide.shapes.title.height
    assert Inches(CHART_BOX[0] + CHART_BOX[2]) <= b.prs.slide_width


def test_safe_render_collects_warning_never_raises():
    b = BasePptxReportBuilder()

    def boom():
        raise ValueError("render exploded")

    result = b.safe_render(boom, label="electropherogram lane 3")
    assert result is None
    assert len(b.warnings) == 1
    assert "electropherogram lane 3" in b.warnings[0]


def test_build_produces_valid_pptx_bytes():
    b = BasePptxReportBuilder()
    b.new_slide("cover")
    b.new_slide("closing")
    out = b.build()
    assert isinstance(out, BytesIO)
    out.seek(0)
    reopened = Presentation(out)
    assert len(reopened.slides._sldIdLst) == 2
