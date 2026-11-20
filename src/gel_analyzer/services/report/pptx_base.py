# gel_analyzer/services/report/pptx_base.py
"""Shared base class for gel-analyzer PowerPoint reports.

Builds on python-pptx's own default template, made a 16:9 deck in code (no template file ships with
Phoresis): the slide is widened, the master's and the layouts' placeholders are rescaled and placed for the
wide slide, and what the default template has no placeholder for (a chart, a wide picture beside its legend)
is placed as a shape at the geometry constants below. Exposes DRY slide helpers (new_slide, set_title,
add_table, add_kv, add_picture_fit, add_section_divider, add_speaker_notes, add_xy_scatter) plus a
render-failure-safe wrapper.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from io import BytesIO

from pptx import Presentation
from pptx.chart.data import XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_VERTICAL_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

from phoresis_core.logging_config import get_logger

from .constants import BODY_FONT, HEADING_FONT, PHORESIS_ACCENT_HEX, saturation_text

logger = get_logger(__name__)

# ── the neutral 16:9 deck ─────────────────────────────────────────
# A 16:9 slide (13.333 x 7.5 in), in EMU: PowerPoint's own "Widescreen".
SLIDE_WIDTH_EMU, SLIDE_HEIGHT_EMU = 12192000, 6858000
SLIDE_WIDTH_IN, SLIDE_HEIGHT_IN = 13.333, 7.5

# Each slide kind of the decks -> the layout of python-pptx's default template it is built on, by name.
LAYOUTS = {
    "cover": "Title Slide",  # centre title + subtitle
    "section": "Section Header",  # title + a text line (its subtitle)
    "title_text": "Title and Content",  # title + body
    "title_chart": "Title Only",  # title; the chart is a shape in CHART_BOX
    "image_text": "Picture with Caption",  # title + PICTURE placeholder + text
    "image_wide": "Title Only",  # title; text left in IMAGE_WIDE_TEXT_BOX, picture right in IMAGE_WIDE_PICTURE_BOX
    "blank": "Blank",
    "closing": "Title Slide",
}

# Boxes on the wide slide, in inches: (left, top, width, height).
# The master's title, every content slide's: it ends at 1.0 in, where the decks' highest content starts.
TITLE_BOX = (0.5, 0.25, 12.33, 0.75)
BODY_BOX = (0.5, 1.4, 12.33, 5.4)  # the master's body
CHART_BOX = (0.5, 1.4, 12.33, 5.4)  # a native chart under the title ("title_chart")
IMAGE_WIDE_TEXT_BOX = (0.5, 1.43, 4.0, 5.24)  # "image_wide": the legend, on the left
IMAGE_WIDE_PICTURE_BOX = (4.67, 1.43, 8.26, 5.24)  # "image_wide": the picture, on the right
SLIDE_NUMBER_BOX = (11.83, 7.02, 1.0, 0.3)  # a slide's number, bottom right
# The placeholders a layout places itself, by layout name then placeholder idx.
LAYOUT_BOXES = {
    "Title Slide": {0: (1.0, 2.3, 11.33, 1.5), 1: (1.0, 3.95, 11.33, 1.6)},
    "Section Header": {0: (1.0, 2.6, 11.33, 1.3), 1: (1.0, 4.0, 11.33, 1.0)},
    "Picture with Caption": {0: TITLE_BOX, 1: (0.5, 1.43, 8.26, 5.24), 2: (9.0, 1.43, 3.83, 5.24)},
}
# A title's size (pt) and alignment by layout name; the others take the default.
TITLE_STYLES = {"Title Slide": (36, PP_ALIGN.CENTER), "Section Header": (32, PP_ALIGN.LEFT)}
TITLE_STYLE_DEFAULT = (26, PP_ALIGN.LEFT)

_ACCENT = RGBColor.from_string(PHORESIS_ACCENT_HEX)  # the app's accent-600 (tokens.css)
_HEADER_FILL = _ACCENT
_HEADER_INK = RGBColor(0xFF, 0xFF, 0xFF)
_PLACEHOLDER_INK = RGBColor(0xB0, 0x30, 0x30)


def _place(shape, box):
    """Put ``shape`` at ``box`` (left, top, width, height in inches)."""
    shape.left, shape.top, shape.width, shape.height = (Inches(value) for value in box)


def new_wide_presentation():
    """python-pptx's default (4:3) template as an empty 16:9 deck: the slide widened, every placeholder that has its
    own position stretched to it, then the master's title and body and the boxes of :data:`LAYOUT_BOXES` placed."""
    prs = Presentation()
    scale = SLIDE_WIDTH_EMU / prs.slide_width
    prs.slide_width, prs.slide_height = SLIDE_WIDTH_EMU, SLIDE_HEIGHT_EMU
    master = prs.slide_master
    for holder in [master, *prs.slide_layouts]:
        for ph in holder.placeholders:
            if ph._element.spPr.xfrm is None:
                continue  # it takes the master's position
            ph.left, ph.width = int(ph.left * scale), int(ph.width * scale)
    for ph in master.placeholders:
        if ph.placeholder_format.type == PP_PLACEHOLDER.TITLE:
            _place(ph, TITLE_BOX)
        elif ph.placeholder_format.type == PP_PLACEHOLDER.BODY:
            _place(ph, BODY_BOX)
    for layout in prs.slide_layouts:
        boxes = LAYOUT_BOXES.get(layout.name, {})
        for ph in layout.placeholders:
            if ph.placeholder_format.idx in boxes:
                _place(ph, boxes[ph.placeholder_format.idx])
    return prs


# A lane's band table, as every report prints it: the band's name ("B3"), its densitometry, its saturation.
BAND_TABLE_HEADERS = ["Band", "Type", "MW (kDa)", "Area", "% Lane", "Saturation"]


def band_table_row(band) -> list[str]:
    """One row of :data:`BAND_TABLE_HEADERS`."""
    return [
        band.name or "-",
        band.band_type,
        f"{band.estimated_mw_kda:.1f}" if band.estimated_mw_kda else "-",
        f"{band.corrected_area:.0f}" if band.corrected_area else "-",
        f"{band.relative_percent_lane:.1f}" if band.relative_percent_lane is not None else "-",
        saturation_text(band),
    ]


class BasePptxReportBuilder:
    """Base PPTX builder on the neutral 16:9 deck (:func:`new_wide_presentation`)."""

    def __init__(self):
        self.prs = new_wide_presentation()
        self.warnings: list[str] = []

    # ── slides ────────────────────────────────────────────────────
    def new_slide(self, key: str):
        layout = self.prs.slide_layouts.get_by_name(LAYOUTS[key])
        return self.prs.slides.add_slide(layout)

    def _title_placeholder(self, slide):
        for ph in slide.placeholders:
            if ph.placeholder_format.type in (
                PP_PLACEHOLDER.TITLE,
                PP_PLACEHOLDER.CENTER_TITLE,
            ):
                return ph
        return None

    def _subtitle_placeholder(self, slide):
        """The slide's subtitle; on a section slide, whose layout has none, its text line."""
        for ph in slide.placeholders:
            if ph.placeholder_format.type == PP_PLACEHOLDER.SUBTITLE:
                return ph
        if slide.slide_layout.name == LAYOUTS["section"]:
            for ph in slide.placeholders:
                if ph.placeholder_format.type == PP_PLACEHOLDER.BODY:
                    return ph
        return None

    def _style_text(self, frame, *, size, color, bold, align, name):
        """The default template's text is 44 pt, centred, in its theme's face: every title and subtitle is set here."""
        frame.word_wrap = True
        for paragraph in frame.paragraphs:
            paragraph.alignment = align
            for run in paragraph.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = color
                run.font.name = name

    def set_title(self, slide, text: str):
        ph = self._title_placeholder(slide)
        if ph is None:
            logger.warning(f"set_title: no title placeholder on slide layout {slide.slide_layout.name!r}")
            return
        ph.text_frame.text = text
        size, align = TITLE_STYLES.get(slide.slide_layout.name, TITLE_STYLE_DEFAULT)
        ph.text_frame.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
        self._style_text(ph.text_frame, size=size, color=self.INK, bold=True, align=align, name=HEADING_FONT)

    def set_subtitle(self, slide, text: str):
        ph = self._subtitle_placeholder(slide)
        if ph is None:
            logger.warning(f"set_subtitle: no subtitle placeholder on slide layout {slide.slide_layout.name!r}")
            return
        ph.text_frame.text = text
        _, align = TITLE_STYLES.get(slide.slide_layout.name, TITLE_STYLE_DEFAULT)
        ph.text_frame.vertical_anchor = MSO_VERTICAL_ANCHOR.TOP
        self._style_text(ph.text_frame, size=16, color=self.MUTED, bold=False, align=align, name=BODY_FONT)

    def add_section_divider(self, title: str, subtitle: str | None = None):
        slide = self.new_slide("section")
        self.set_title(slide, title)
        if subtitle:
            self.set_subtitle(slide, subtitle)
        return slide

    # ── the builders' slides (the densitometry and comparison decks share them) ──
    def _new_slide(self, layout_key: str = "title_text"):
        # The layout's own title placeholder (set via _add_header_bar). Strip only
        # the empty BODY/OBJECT placeholders (their "click to add text" prompt).
        slide = self.new_slide(layout_key)
        for ph in list(slide.placeholders):
            if ph.placeholder_format.type in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT):
                ph._element.getparent().remove(ph._element)
        self.slide_number = getattr(self, "slide_number", 0) + 1
        return slide

    def _add_header_bar(self, slide, title: str, height: float = 1.0):
        # The layout's title placeholder (was a hand-drawn bar pre-overhaul).
        # `height` kept only for call-site signature compat.
        self.set_title(slide, title)

    def _add_slide_number(self, slide):
        # build() numbers every slide but the first (the default template's slide-number placeholder is not
        # carried onto a slide): nothing to draw here. Kept for the call sites.
        pass

    # ── tables ────────────────────────────────────────────────────
    # The builders' data tables: the row height they draw, and the lowest a table may reach (above the master's
    # footer and logo). A table that would run past it continues on another slide: no row is ever dropped.
    TABLE_ROW_HEIGHT_IN = 0.28
    TABLE_BOTTOM_IN = 6.9
    # A lane's band table: short cells on one line, in two columns -- the lane's slide holds 14 bands under its
    # electropherogram, a continuation slide 36.
    BAND_ROW_HEIGHT_IN = 0.28
    BAND_TABLE_TOP_IN = 4.45

    # The compact table's inks: a plain header over a rule in the app's accent, hairlines, a faint zebra (the pages'
    # tables).
    TABLE_RULE = PHORESIS_ACCENT_HEX
    TABLE_HAIRLINE = "E5E7EB"
    TABLE_ZEBRA = RGBColor(0xF7, 0xF7, 0xF9)
    TABLE_HIGHLIGHT = RGBColor(0xFC, 0xE4, 0xE4)
    TABLE_WIDTH_IN = 12.33

    @staticmethod
    def drop_empty_columns(headers, rows, optional):
        """``(headers, rows)`` without the ``optional`` columns no row fills ("", "-", "—"): a column of dashes on
        every lane of a gel took a slide's width for nothing."""
        keep = [
            j
            for j, header in enumerate(headers)
            if header not in optional or any(str(row[j]).strip() not in ("", "-", "—", "None") for row in rows)
        ]
        return [headers[j] for j in keep], [[row[j] for j in keep] for row in rows]

    @staticmethod
    def _numeric(text) -> bool:
        cleaned = str(text).replace("%", "").replace(",", "").strip()
        try:
            float(cleaned)
        except ValueError:
            return False
        return True

    def _column_widths(self, headers, rows, width):
        """Inches per column, from its longest text: the natural widths when they fit ``width``, else scaled to it."""
        natural = []
        for j, header in enumerate(headers):
            longest = max([len(str(header))] + [len(str(row[j])) for row in rows])
            natural.append(max(0.45, min(3.6, 0.16 + 0.07 * longest)))
        if sum(natural) <= width:
            return natural
        scale = width / sum(natural)
        return [max(0.4, w * scale) for w in natural]

    @staticmethod
    def _cell_rule(cell, edge: str, color, width_pt: float = 0):
        """A cell's ``edge`` border ("L", "R", "T", "B") as an a:lnX element, placed before the cell's fill (the
        schema's order); ``color`` None draws none -- without it PowerPoint draws its default black grid line."""
        tc_pr = cell._tc.get_or_add_tcPr()
        tag = qn(f"a:ln{edge}")
        for old in tc_pr.findall(tag):
            tc_pr.remove(old)
        line = OxmlElement(f"a:ln{edge}")
        if color is None:
            line.set("w", "0")
            line.append(OxmlElement("a:noFill"))
        else:
            line.set("w", str(int(Pt(width_pt))))
            fill = OxmlElement("a:solidFill")
            rgb = OxmlElement("a:srgbClr")
            rgb.set("val", color)
            fill.append(rgb)
            line.append(fill)
        fills = [
            child
            for child in tc_pr
            if child.tag.split("}")[1] in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")
        ]
        if fills:
            fills[0].addprevious(line)
        else:
            tc_pr.append(line)

    def _add_data_table(
        self,
        slide,
        headers,
        rows,
        top=1.5,
        max_rows=None,
        row_height=None,
        *,
        left=0.5,
        width=None,
        font_size=9.0,
        highlight_rows=(),
    ):
        """A compact table, as the app's pages draw theirs: a plain bold header over an accent rule, hairlines between
        rows, a faint zebra, columns as wide as their text, numbers right-aligned. The template's table style (a
        banded first row) is dropped. ``highlight_rows``: body rows filled light red (an out-of-spec control).
        Returns the number of rows written (``max_rows`` at most)."""
        rows = [["" if value is None else str(value) for value in row] for row in rows]
        if max_rows is not None:
            rows = rows[:max_rows]
        row_height = row_height or self.TABLE_ROW_HEIGHT_IN
        widths = self._column_widths(headers, rows, width or self.TABLE_WIDTH_IN - (left - 0.5))
        shape = slide.shapes.add_table(
            len(rows) + 1,
            len(headers),
            Inches(left),
            Inches(top),
            Inches(sum(widths)),
            Inches((len(rows) + 1) * row_height),
        )
        table = shape.table
        tbl_pr = table._tbl.tblPr
        for child in list(tbl_pr):
            if child.tag.endswith("}tableStyleId"):
                tbl_pr.remove(child)
        for flag in ("firstRow", "bandRow"):
            tbl_pr.set(flag, "0")
        for j, w in enumerate(widths):
            table.columns[j].width = Inches(w)
        for row in table.rows:
            row.height = Inches(row_height)
        numeric = {
            j
            for j in range(len(headers))
            if any(row[j] not in ("", "-", "—") for row in rows)
            and all(self._numeric(row[j]) for row in rows if row[j] not in ("", "-", "—"))
        }
        highlight = set(highlight_rows)
        for i, values in enumerate([list(map(str, headers))] + rows):
            for j, value in enumerate(values):
                cell = table.cell(i, j)
                cell.margin_left = cell.margin_right = Inches(0.06)
                cell.margin_top = cell.margin_bottom = Inches(0.03)
                cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
                cell.text = value
                for edge in ("L", "R", "T"):
                    self._cell_rule(cell, edge, None)
                if i == 0:
                    self._cell_rule(cell, "B", self.TABLE_RULE, 1.5)
                    cell.fill.background()
                else:
                    self._cell_rule(cell, "B", self.TABLE_HAIRLINE, 0.5)
                    if (i - 1) in highlight:
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = self.TABLE_HIGHLIGHT
                    elif i % 2 == 0:
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = self.TABLE_ZEBRA
                    else:
                        cell.fill.background()
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.alignment = PP_ALIGN.RIGHT if j in numeric else PP_ALIGN.LEFT
                    # An empty cell has no run: its paragraph's own size keeps it from the default 18 pt (a tall row).
                    paragraph.font.size = Pt(font_size)
                    for run in paragraph.runs:
                        run.font.size = Pt(font_size - 0.5 if i == 0 else font_size)
                        run.font.bold = i == 0
                        run.font.color.rgb = self.MUTED if i == 0 else self.INK
                        run.font.name = HEADING_FONT if i == 0 else BODY_FONT
        return len(rows)

    def _add_kv_table(self, slide, data, top: float = 1.5):
        """Label / value pairs as a compact two-column table without a header: grey labels, hairlines."""
        rows = [[str(label), "" if value in (None, "") else str(value)] for label, value in data]
        shape = slide.shapes.add_table(len(rows), 2, Inches(0.5), Inches(top), Inches(9.0), Inches(len(rows) * 0.34))
        table = shape.table
        tbl_pr = table._tbl.tblPr
        for child in list(tbl_pr):
            if child.tag.endswith("}tableStyleId"):
                tbl_pr.remove(child)
        for flag in ("firstRow", "bandRow"):
            tbl_pr.set(flag, "0")
        table.columns[0].width, table.columns[1].width = Inches(2.6), Inches(6.4)
        for i, (label, value) in enumerate(rows):
            table.rows[i].height = Inches(0.34)
            for j, text in enumerate((label, value)):
                cell = table.cell(i, j)
                cell.text = text
                cell.fill.background()
                for edge in ("L", "R", "T"):
                    self._cell_rule(cell, edge, None)
                self._cell_rule(cell, "B", self.TABLE_HAIRLINE, 0.5)
                cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
                cell.text_frame.paragraphs[0].font.size = Pt(11)
                for run in cell.text_frame.paragraphs[0].runs:
                    run.font.size = Pt(11)
                    run.font.bold = j == 0
                    run.font.color.rgb = self.MUTED if j == 0 else self.INK
                    run.font.name = HEADING_FONT if j == 0 else BODY_FONT

    def _add_band_tables(self, slide, title, bands, *, top=None, columns=(0.5, 6.9), width=6.0):
        """A lane's band table on its slide -- from ``top`` (inches; under the electropherogram by default), in
        ``columns`` side by side (each one's left edge, ``width`` wide) -- then on "<title> — bands (continued)"
        slides, two columns each. No band is ever left out (the table once kept the first 8 and ran past the foot
        of the slide)."""
        rows = [band_table_row(band) for band in bands]
        top, height = top or self.BAND_TABLE_TOP_IN, self.BAND_ROW_HEIGHT_IN
        first = self.rows_fitting(top, height)
        more = self.rows_fitting(1.4, height)
        pages = [(slide, top, first, columns, width)]
        offset = first * len(columns)
        while offset < len(rows):
            continued = self._new_slide()
            self._add_header_bar(continued, f"{title} — bands (continued)")
            pages.append((continued, 1.4, more, (0.5, 6.9), 6.0))
            offset += more * 2
        start = 0
        for page, page_top, per_column, page_columns, page_width in pages:
            for left in page_columns:
                chunk = rows[start : start + per_column]
                if not chunk:
                    break
                self._add_data_table(
                    page, BAND_TABLE_HEADERS, chunk, top=page_top, left=left, width=page_width, row_height=height
                )
                start += per_column

    # The lane slide in the identity card's look: the lane's figure on the left, its facts and bands on the right.
    LANE_FIGURE_BOX = (0.4, 1.3, 7.35, 5.45)  # left, top, width, height (inches)
    LANE_COLUMN_LEFT, LANE_COLUMN_WIDTH = 7.95, 4.95

    def add_lane_panel(self, slide, title, lane, facts, figure):
        """``figure`` (a PNG buffer, or None) fitted in the left box; ``facts`` (label, value) and the lane's band
        table in the right column, the table continued on further slides."""
        left, top, width, height = self.LANE_FIGURE_BOX
        if figure is not None:
            self.add_picture_fit(slide, figure, left=left, top=top, max_width=width, max_height=height, center=True)
        else:
            self.add_render_placeholder(slide, f"Lane {lane.lane_number} figure", left=left, top=3.0, width=width)
        self.add_facts(slide, facts, left=self.LANE_COLUMN_LEFT, top=top, width=self.LANE_COLUMN_WIDTH, title="LANE")
        if lane.bands:
            table_top = top + 0.3 * (len(facts) + 1) + 0.25
            self._add_band_tables(
                slide,
                title,
                lane.bands,
                top=table_top,
                columns=(self.LANE_COLUMN_LEFT,),
                width=self.LANE_COLUMN_WIDTH,
            )

    @classmethod
    def rows_fitting(cls, top_in: float, row_height_in: float | None = None) -> int:
        """How many body rows, under a header row, fit between ``top_in`` and the table bottom; one at least."""
        return max(1, int((cls.TABLE_BOTTOM_IN - top_in) / (row_height_in or cls.TABLE_ROW_HEIGHT_IN)) - 1)

    def add_table(
        self,
        slide,
        rows: int,
        cols: int,
        *,
        data: Sequence[Sequence[str]] | None = None,
        col_widths: Sequence[float] | None = None,
        numeric_cols: Sequence[int] = (),
        max_rows: int | None = None,
        overflow_note: str = "+{n} more",
        left: float = 0.5,
        top: float = 1.5,
        width: float = 12.0,
        height: float | None = None,
    ):
        """Add a plain table. `data` (list of row lists) is optional;
        when given it is written in (after pagination). The header row is
        row 0. Numeric cols are right-aligned + vertically centered.
        """
        body_rows_available = rows - 1  # exclude header
        truncated = max_rows is not None and body_rows_available > max_rows
        if truncated:
            hidden = body_rows_available - max_rows
            render_rows = 1 + max_rows + 1  # header + capped body + overflow row
        else:
            render_rows = rows

        if height is None:
            height = max(0.4, 0.35 * render_rows)

        gf = slide.shapes.add_table(
            render_rows,
            cols,
            Inches(left),
            Inches(top),
            Inches(width),
            Inches(height),
        )
        table = gf.table

        # Clear the default tableStyleId ("Medium Style 2 - Accent 1").
        tblPr = table._tbl.tblPr
        if tblPr is not None:
            for child in list(tblPr):
                if child.tag.endswith("}tableStyleId"):
                    tblPr.remove(child)

        # Per-column widths.
        if col_widths:
            for i, w in enumerate(col_widths):
                if i < cols:
                    table.columns[i].width = Inches(w)

        # Write data with pagination.
        if data is not None:
            self._fill_table(table, data, max_rows, truncated, overflow_note, cols, numeric_cols)
        else:
            # Caller fills cells; still apply numeric alignment lazily is
            # not possible, so apply alignment to all body cells in numeric
            # cols now (text set later still keeps paragraph alignment).
            overflow_row_idx = len(table.rows) - 1 if truncated else None
            for r in range(1, len(table.rows)):
                for c in numeric_cols:
                    cell = table.cell(r, c)
                    cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
                    cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
            # Write the overflow note text into the last row when truncated.
            if truncated and overflow_row_idx is not None:
                hidden = body_rows_available - max_rows
                table.cell(overflow_row_idx, 0).text = overflow_note.format(n=hidden)
        return gf

    def _fill_table(self, table, data, max_rows, truncated, overflow_note, cols, numeric_cols):
        header = data[0]
        body = data[1:]
        if truncated:
            body = body[:max_rows]
        rendered = [header] + list(body)
        if truncated:
            hidden = len(data) - 1 - max_rows
            rendered.append([overflow_note.format(n=hidden)] + [""] * (cols - 1))

        for r, row in enumerate(rendered):
            for c in range(cols):
                cell = table.cell(r, c)
                cell.text = str(row[c]) if c < len(row) else ""
                cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
                if r > 0 and c in numeric_cols:
                    cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    # ── the page's summary: cards, checks, facts ─────────────────
    # The workbench's tones (analysis_detail's cards: ok / warn / bad) and the summary's inks, on the white template.
    TONES = {"ok": RGBColor(0x15, 0x80, 0x3D), "warn": RGBColor(0xB4, 0x53, 0x09), "bad": RGBColor(0xB9, 0x1C, 0x1C)}
    INK = RGBColor(0x24, 0x26, 0x2B)
    MUTED = RGBColor(0x6B, 0x72, 0x80)
    HAIRLINE = RGBColor(0xD9, 0xDC, 0xE1)
    CHECK_DETAIL_CHARS = 220  # a check's detail beyond this is cut: the page holds it whole

    @staticmethod
    def _run(paragraph, text, *, size, color, bold=False, name=HEADING_FONT):
        run = paragraph.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = name
        return run

    def add_cards(
        self, slide, cards, *, left: float = 0.5, top: float = 1.35, width: float = 12.33, height: float = 1.05
    ):
        """The page's metric cards (``analysis_detail``'s ``cards``) in one row: label, value (in its tone), sub."""
        cards = list(cards)[:6]
        if not cards:
            return
        gap = 0.15
        card_width = (width - gap * (len(cards) - 1)) / len(cards)
        for i, card in enumerate(cards):
            shape = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE,
                Inches(left + i * (card_width + gap)),
                Inches(top),
                Inches(card_width),
                Inches(height),
            )
            shape.adjustments[0] = 0.08
            shape.fill.background()
            shape.line.color.rgb = self.TONES["warn"] if card.get("tone") == "warn" else self.HAIRLINE
            shape.line.width = Pt(0.75)
            shape.shadow.inherit = False
            frame = shape.text_frame
            frame.word_wrap = True
            frame.vertical_anchor = MSO_VERTICAL_ANCHOR.TOP
            for side in ("margin_left", "margin_right"):
                setattr(frame, side, Inches(0.12))
            frame.margin_top = frame.margin_bottom = Inches(0.06)
            label = frame.paragraphs[0]
            label.alignment = PP_ALIGN.LEFT
            self._run(label, str(card["label"]).upper(), size=8, color=self.MUTED, bold=True)
            value = frame.add_paragraph()
            self._run(value, str(card["value"]), size=20, color=self.TONES.get(card.get("tone"), self.INK), bold=True)
            if card.get("sub"):
                sub = frame.add_paragraph()
                self._run(sub, str(card["sub"]), size=9, color=self.MUTED, name=BODY_FONT)

    def add_checks(self, slide, checks, *, left: float, top: float, width: float, max_items: int = 6):
        """The page's "To check" items (``analysis_detail.build_checks``, warnings first): a mark, the title, the detail
        (cut at :attr:`CHECK_DETAIL_CHARS`); past ``max_items``, a line says how many more the page lists."""
        checks = list(checks)
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(6.9 - top))
        frame = box.text_frame
        frame.word_wrap = True
        self._run(frame.paragraphs[0], "TO CHECK", size=9, color=self.MUTED, bold=True)
        if not checks:
            self._run(frame.add_paragraph(), "Nothing to check.", size=11, color=self.TONES["ok"])
            return
        for check in checks[:max_items]:
            title = frame.add_paragraph()
            title.space_before = Pt(6)
            warn = check.get("level") == "warn"
            self._run(
                title, "⚠ " if warn else "ℹ ", size=11, color=self.TONES["warn"] if warn else self.MUTED, bold=True
            )
            self._run(title, str(check["title"]), size=11, color=self.INK, bold=True)
            detail = str(check.get("detail") or "")
            if len(detail) > self.CHECK_DETAIL_CHARS:
                detail = detail[: self.CHECK_DETAIL_CHARS].rsplit(" ", 1)[0] + " …"
            if detail:
                self._run(frame.add_paragraph(), detail, size=9, color=self.MUTED, name=BODY_FONT)
        if len(checks) > max_items:
            more = len(checks) - max_items
            self._run(
                frame.add_paragraph(),
                f"+ {more} more on the analysis page",
                size=9,
                color=self.MUTED,
                bold=True,
            )

    def add_facts(self, slide, facts, *, left: float, top: float, width: float, title: str = "ANALYSIS"):
        """Label / value lines under a small heading: the summary's facts beside its checks."""
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(6.9 - top))
        frame = box.text_frame
        frame.word_wrap = True
        self._run(frame.paragraphs[0], title, size=9, color=self.MUTED, bold=True)
        for label, value in facts:
            line = frame.add_paragraph()
            line.space_before = Pt(4)
            self._run(line, f"{label}  ", size=10, color=self.MUTED, bold=True)
            self._run(line, str(value) if value not in (None, "") else "—", size=10, color=self.INK, name=BODY_FONT)

    def add_kv(self, slide, pairs: Iterable[tuple], *, left: float = 0.5, top: float = 1.5, width: float = 8.0):
        pairs = list(pairs)
        data = [["Field", "Value"]] + [[str(k), str(v)] for k, v in pairs]
        return self.add_table(
            slide,
            len(data),
            2,
            data=data,
            col_widths=[width * 0.35, width * 0.65],
            left=left,
            top=top,
            width=width,
        )

    # ── pictures ──────────────────────────────────────────────────
    def add_picture_fit(
        self, slide, image, *, left: float, top: float, max_width: float, max_height: float, center: bool = False
    ):
        """Aspect-locked picture placement inside a max box (its top-left corner, or its centre with ``center``)."""
        from PIL import Image as PILImage

        if hasattr(image, "seek"):
            image.seek(0)
            iw, ih = PILImage.open(image).size
            image.seek(0)
        else:
            iw, ih = PILImage.open(image).size

        box_w, box_h = Inches(max_width), Inches(max_height)
        scale = min(box_w / iw, box_h / ih)
        draw_w = Emu(int(iw * scale))
        draw_h = Emu(int(ih * scale))
        x, y = Inches(left), Inches(top)
        if center:
            x, y = Emu(x + (box_w - draw_w) // 2), Emu(y + (box_h - draw_h) // 2)
        return slide.shapes.add_picture(image, x, y, width=draw_w, height=draw_h)

    def add_figure_slide(self, title: str, picture, legend: Sequence[str], *, placeholder_label: str = "Figure"):
        """An "image_wide" slide: ``picture`` (a PNG buffer, or None) fitted and centred in
        :data:`IMAGE_WIDE_PICTURE_BOX`, ``legend`` lines in :data:`IMAGE_WIDE_TEXT_BOX` beside it. Both are shapes: the
        default template has no such layout, and a picture placeholder would crop the picture to fill its frame."""
        slide = self.new_slide("image_wide")
        self.set_title(slide, title)
        if legend:
            frame = slide.shapes.add_textbox(*(Inches(value) for value in IMAGE_WIDE_TEXT_BOX)).text_frame
            frame.word_wrap = True
            for i, line in enumerate(legend):
                paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                paragraph.space_after = Pt(6)
                self._run(paragraph, line, size=11, color=self.INK, name=BODY_FONT)
        left, top, width, height = (Inches(value) for value in IMAGE_WIDE_PICTURE_BOX)
        if picture is None:
            self.add_render_placeholder(
                slide, placeholder_label, left=Emu(left).inches, top=3.0, width=Emu(width).inches
            )
            return slide
        from PIL import Image as PILImage

        picture.seek(0)
        iw, ih = PILImage.open(picture).size
        picture.seek(0)
        scale = min(width / iw, height / ih)
        draw_w, draw_h = int(iw * scale), int(ih * scale)
        slide.shapes.add_picture(
            picture, Emu(left + (width - draw_w) // 2), Emu(top + (height - draw_h) // 2), Emu(draw_w), Emu(draw_h)
        )
        return slide

    def add_caption(self, slide, text: str, *, top: float = 6.45):
        """A one-line caption under a figure, in the summary's muted ink."""
        box = slide.shapes.add_textbox(Inches(0.5), Inches(top), Inches(12.33), Inches(0.35))
        box.text_frame.word_wrap = True
        self._run(box.text_frame.paragraphs[0], text, size=10, color=self.MUTED, name=BODY_FONT)

    # ── notes ─────────────────────────────────────────────────────
    def add_speaker_notes(self, slide, text: str):
        notes = slide.notes_slide  # created lazily
        tf = notes.notes_text_frame
        if tf is None:  # C6 guard
            logger.warning("add_speaker_notes: notes_text_frame is None; skipped")
            return
        tf.text = text

    # ── native charts ─────────────────────────────────────────────
    def add_xy_scatter(self, slide, *, series, x_title: str, y_title: str):
        """Insert a native XY_SCATTER chart in :data:`CHART_BOX`, under the slide's title (the default template has
        no chart placeholder: the chart is a shape). `series` = [(name, [(x, y), ...]), ...]."""
        chart_data = XyChartData()
        for name, points in series:
            s = chart_data.add_series(name)
            for x, y in points:
                s.add_data_point(x, y)
        gf = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, *(Inches(value) for value in CHART_BOX), chart_data)
        chart = gf.chart
        chart.has_title = False
        return chart

    # ── robustness ────────────────────────────────────────────────
    def safe_render(self, fn: Callable, *, label: str):
        """Run a render callable; on failure collect a warning and return
        None (caller draws a visible placeholder). Never raises."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — observability must not break
            logger.warning(f"safe_render[{label}]: {exc}")
            self.warnings.append(f"{label}: {exc}")
            return None

    def add_render_placeholder(
        self, slide, label: str, *, left: float = 1.0, top: float = 3.0, width: float = 8.0, height: float = 1.0
    ):
        """Visible 'could not render' box (never a silent grey gap)."""
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        p = box.text_frame.paragraphs[0]
        p.text = f"[ {label} could not be rendered ]"
        p.font.size = Pt(14)
        p.font.color.rgb = _PLACEHOLDER_INK
        p.alignment = PP_ALIGN.CENTER
        return box

    # ── output ────────────────────────────────────────────────────
    def _number_slides(self):
        """Each slide's number in :data:`SLIDE_NUMBER_BOX`, the first (the cover) left bare; once per deck."""
        if getattr(self, "_slides_numbered", False):
            return
        self._slides_numbered = True
        for number, slide in enumerate(self.prs.slides, 1):
            if number == 1:
                continue
            box = slide.shapes.add_textbox(*(Inches(value) for value in SLIDE_NUMBER_BOX))
            box.name = "Slide number"
            paragraph = box.text_frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.RIGHT
            self._run(paragraph, str(number), size=9, color=self.MUTED, name=BODY_FONT)

    def build(self) -> BytesIO:
        self._number_slides()
        buf = BytesIO()
        self.prs.save(buf)
        buf.seek(0)
        return buf
