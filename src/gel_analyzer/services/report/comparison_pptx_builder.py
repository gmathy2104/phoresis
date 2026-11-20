"""
PowerPoint builder for gel lane comparison reports.

Thin subclass of BasePptxReportBuilder — slides are built on the neutral
16:9 deck's layouts (pptx_base.LAYOUTS) via new_slide()/set_title(), not
hand-drawn bars (as the densitometry deck).
"""

from io import BytesIO

from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from phoresis_core.logging_config import get_logger

from .comparison_data_collector import ComparisonReportData
from .constants import (
    BODY_FONT,
    GEL_VARIANT_TITLES,
    GEL_VARIANTS_CANONICAL_ORDER,
    GEL_VARIANTS_DEFAULT,
    HEADING_FONT,
    MUTED_GRAY,
    PHORESIS_ACCENT,
    PHORESIS_ACCENT_DARK,
    PHORESIS_INK,
    READOUT_METHODOLOGY,
)
from .digital_gel import render_digital_gel
from .page_rows import cell_text, headline_text, mean_purity_text, sample_text
from .pptx_base import BasePptxReportBuilder

logger = get_logger(__name__)

# Brand palette (text accents only — the titles are the layouts' own), from constants.py
_ACCENT = RGBColor(*PHORESIS_ACCENT)
_ACCENT_DARK = RGBColor(*PHORESIS_ACCENT_DARK)
_DARK = RGBColor(*PHORESIS_INK)
_GREY = RGBColor(*MUTED_GRAY)
_GREY_LIGHT = RGBColor(0xF8, 0xFA, 0xFC)

# Under the digital gel: what its amber dot and its placement mean (digital_gel.py).
DIGITAL_GEL_CAPTION = (
    "Amber dot: a lane whose bands have no MW. Unless every band has an MW, each band sits at its position on its "
    "gel, and the kDa labels are the ladder's markers."
)

# Sections not applicable to PowerPoint
_PPTX_SKIP_SECTIONS = set()  # All sections can produce slides


class ComparisonPowerPointBuilder(BasePptxReportBuilder):
    """
    Lane Comparison PowerPoint report — thin subclass of
    BasePptxReportBuilder. Slides are built on the neutral 16:9 deck's layouts
    (cover/section/title_text/title_chart/image_wide: pptx_base.LAYOUTS) via
    new_slide()/set_title(), not hand-drawn bars.
    """

    def __init__(
        self,
        data: ComparisonReportData,
        sections: list[str] | None = None,
        band_overlay: bool = True,
        gel_variants: list[str] | None = None,
    ):
        super().__init__()  # the neutral 16:9 deck in self.prs (+ self.warnings)
        self.data = data
        self.sections = sections
        self.band_overlay = band_overlay
        # Selected gel-image variants (spec D3). Normalise to the canonical
        # order; default to ["FULL"] when absent/empty.
        self.gel_variants = self._normalize_gel_variants(gel_variants)
        self.slide_number = 0

    @staticmethod
    def _normalize_gel_variants(gel_variants: list[str] | None) -> list[str]:
        """Keep only known variants, in canonical order; default ["FULL"]."""
        selected = set(gel_variants or [])
        ordered = [v for v in GEL_VARIANTS_CANONICAL_ORDER if v in selected]
        return ordered or list(GEL_VARIANTS_DEFAULT)

    def _should_include(self, section_key: str) -> bool:
        if section_key in _PPTX_SKIP_SECTIONS:
            return False
        if self.sections is None:
            return True
        return section_key in self.sections

    # ── Shared helpers ────────────────────────────────────────────

    def _add_image_to_slide(self, slide, image_buf, top=1.5, max_width=11.0, max_height=5.5):
        """Add an image centered on the slide."""
        if not image_buf:
            return
        from PIL import Image as PILImage

        image_buf.seek(0)
        img = PILImage.open(image_buf)
        w, h = img.size
        aspect = w / h

        if aspect > max_width / max_height:
            display_w = max_width
            display_h = display_w / aspect
        else:
            display_h = max_height
            display_w = display_h * aspect

        left = (13.33 - display_w) / 2
        image_buf.seek(0)
        slide.shapes.add_picture(
            image_buf,
            Inches(left),
            Inches(top),
            Inches(display_w),
            Inches(display_h),
        )

    # ── Slide builders ────────────────────────────────────────────

    def _add_title_slide(self):
        # The deck's cover ('Title Slide') — no hand-drawn bar.
        slide = self.new_slide("cover")
        self.slide_number += 1
        self.set_title(slide, "Lane Comparison Report")
        self.set_subtitle(slide, self.data.name or "")

        # Keep the key facts (previously printed on the cover) as speaker notes
        # so the cover stays clean/native; the Overview slide lists them too.
        self.add_speaker_notes(
            slide,
            f"Lanes: {self.data.lane_count}  |  Assays: {self._assays_text()}  |  "
            f"Calibrated: {self.data.calibrated_count}/{self.data.lane_count}\n"
            f"Created by: {self.data.created_by_name}  |  {self.data.created_at}\n"
            f"Report generated: {self.data.report_generated_at}  |  By: {self.data.report_generated_by}",
        )

    def _assays_text(self) -> str:
        """The comparison's kinds (assays), as its page names them."""
        return ", ".join(kind.label for kind in self.data.kinds) or "None"

    def _lane_title(self, index, lane) -> str:
        """``<position> · L<lane number> · <sample>``: the lane's place in the comparison, then on its gel."""
        title = f"{index} · L{lane.lane_number} · {sample_text(lane)}"
        return f"{title} (reference)" if lane.is_reference else title

    def _add_overview_slide(self):
        slide = self._new_slide()
        self._add_header_bar(slide, "Comparison Overview")

        calibration_status = (
            f"All lanes calibrated ({self.data.calibrated_count})"
            if self.data.all_calibrated
            else f"{self.data.calibrated_count} of {self.data.lane_count} lanes calibrated"
        )

        data = [
            ("Name", self.data.name),
            ("Description", self.data.description or "N/A"),
            ("Lane Count", str(self.data.lane_count)),
            ("Assays", self._assays_text()),
            ("Calibration", calibration_status),
        ]
        # The mean purity of each purity kind, over the lanes compared (services/mean_purity.py).
        data += [(f"Mean purity · {kind.label}", mean_purity_text(kind.mean)) for kind in self.data.kinds if kind.mean]
        data += [
            ("Created By", self.data.created_by_name),
            ("Created Date", self.data.created_at),
            ("Public", "Yes" if self.data.is_public else "No"),
        ]
        self._add_kv_table(slide, data)
        self._add_slide_number(slide)

    def _add_sample_summary_slides(self):
        """One table per kind (assay), as the comparison page groups its lanes: the kind's readout columns with the
        page's cells (page_rows), never one "Purity" column for a purity and a western's POI share together."""
        positions = {id(lane): i for i, lane in enumerate(self.data.lanes, 1)}
        for kind in self.data.kinds:
            headers = ["#", "Sample", "Analysis", "Lane #", "Condition", "Load (µg)"]
            headers += [column["label"] for column in kind.columns]
            flagged = any(lane.saturated_bands for lane in kind.lanes)
            headers += ["Saturated"] if flagged else []
            rows = []
            for lane in kind.lanes:
                rows.append(
                    [
                        str(positions[id(lane)]),
                        sample_text(lane) + (" (REF)" if lane.is_reference else ""),
                        lane.analysis_name[:25],
                        str(lane.lane_number),
                        lane.condition or "-",
                        f"{lane.protein_load_ug:.1f}" if lane.protein_load_ug is not None else "",
                    ]
                    + [cell_text(lane, column["key"]) for column in kind.columns]
                    + (["⚠ " + ", ".join(lane.saturated_bands) if lane.saturated_bands else ""] if flagged else [])
                )

            # Condition and load only where a lane has one; as many rows a slide as fit.
            headers, rows = self.drop_empty_columns(headers, rows, {"Condition", "Load (µg)"})
            page_size = self.rows_fitting(1.5)
            for offset in range(0, len(rows), page_size):
                slide = self._new_slide()
                title = "Sample Summary" if len(self.data.kinds) == 1 else f"Sample Summary — {kind.label}"
                if len(rows) > page_size:
                    title += f" (Page {offset // page_size + 1})"
                self._add_header_bar(slide, title)
                self._add_data_table(slide, headers, rows[offset : offset + page_size])
                self._add_slide_number(slide)

    def _add_gel_variant_slides(self):
        """The SELECTED gel-image variants PER COMPARED ANALYSIS (spec D3/D8/§Ph2), in the whole-gel look of the app's
        "Full gel" tile (gel_figure), drawing that analysis's compared lanes on its own gel image, with its ladder's kDa
        and its kind's readout; the legend in the text area beside. Canonical order LANES_ONLY -> KEY_BANDS -> FULL;
        default ["FULL"]."""
        from .gel_figure import legend_lines
        from .gel_overlay import GelOverlayVariant

        # Group lanes by source analysis, preserving first-seen order.
        analyses: list[tuple] = []  # (analysis_id, analysis_name, gel_image_id, lanes)
        seen: dict = {}
        for lane in self.data.lanes:
            aid = lane.analysis_id
            if aid not in seen:
                seen[aid] = len(analyses)
                analyses.append((aid, lane.analysis_name, lane.gel_image_id, []))
            analyses[seen[aid]][3].append(lane)

        for analysis_id, analysis_name, gel_image_id, lanes in analyses:
            if not gel_image_id:
                continue
            kind = self.data.kind_of(lanes[0])
            readout = kind.readout if kind else ""
            ticks = self.data.mw_ticks.get(str(analysis_id), [])
            short_name = (analysis_name or "Analysis")[:28]
            saturated = any(band.saturated for lane in lanes for band in lane.bands)
            for label in self.gel_variants:
                variant = GelOverlayVariant(label)
                picture = self.safe_render(
                    lambda gid=gel_image_id, ls=lanes, v=variant, r=readout, t=ticks: self._render_gel_variant(
                        gid, ls, v, r, t
                    ),
                    label=f"gel image {short_name} {label}",
                )
                self.add_figure_slide(
                    f"Gel image — {short_name} — {GEL_VARIANT_TITLES[label]}",
                    picture,
                    legend_lines(variant, readout, has_ticks=bool(ticks), has_saturated=saturated),
                    placeholder_label=f"Gel image ({short_name} {GEL_VARIANT_TITLES[label]})",
                )
                self.slide_number += 1

    def _add_digital_gel_slide(self):
        """Add side-by-side digital gel image slide."""
        slide = self._new_slide()
        self._add_header_bar(slide, "Side-by-Side Digital Gel")

        digital_buf = render_digital_gel(
            self.data.lanes,
            calibration=None,
            footer_field="gel_type",
            exclude_codes=(),  # comparison view must NOT filter EMPTY lanes (mirrors Word builder)
        )

        if digital_buf:
            self._add_image_to_slide(slide, digital_buf, top=1.4, max_height=4.9)
            self.add_caption(slide, DIGITAL_GEL_CAPTION)
        else:
            txbox = slide.shapes.add_textbox(
                Inches(4),
                Inches(3.5),
                Inches(5),
                Inches(0.5),
            )
            txbox.text_frame.paragraphs[0].text = "No digital gel data available"
            txbox.text_frame.paragraphs[0].font.color.rgb = _GREY

        self._add_slide_number(slide)

    def _add_poi_purity_slide(self):
        """The chart of each kind's readout (readout_chart), over that kind's lanes: a purity kind with its mean, a
        western with its own values -- never one purity chart across assays."""
        from .readout_chart import chart_title, render_readout_chart

        for kind in self.data.kinds:
            title = chart_title(kind.readout, kind.lanes)
            if title is None:
                continue
            slide = self._new_slide()
            self._add_header_bar(slide, title if len(self.data.kinds) == 1 else f"{title} — {kind.label}")
            mean = None
            if kind.mean is not None and kind.mean.value is not None:
                mean = (kind.mean.value, f"Mean {mean_purity_text(kind.mean)}")
            chart_buf = render_readout_chart(
                kind.readout, kind.lanes, mean=mean, figsize=(10, 4.5), dpi=150, dark_theme=False
            )
            if chart_buf:
                self._add_image_to_slide(slide, chart_buf, top=1.4, max_height=5.8)
            else:
                txbox = slide.shapes.add_textbox(
                    Inches(4),
                    Inches(3.5),
                    Inches(5),
                    Inches(0.5),
                )
                txbox.text_frame.paragraphs[0].text = "No lane value to chart yet"
                txbox.text_frame.paragraphs[0].font.color.rgb = _GREY
            self._add_slide_number(slide)

    def _add_band_comparison_slides(self):
        """Add MW-clustered band comparison table slides."""
        from .comparison_builder import ComparisonReportBuilder

        builder = ComparisonReportBuilder.__new__(ComparisonReportBuilder)
        builder.data = self.data
        clusters = builder._cluster_bands_by_mw(self.data.mw_tolerance_pct)

        if not clusters:
            slide = self._new_slide()
            self._add_header_bar(slide, "Band Comparison")
            txbox = slide.shapes.add_textbox(
                Inches(4),
                Inches(3.5),
                Inches(5),
                Inches(0.5),
            )
            txbox.text_frame.paragraphs[0].text = "No calibrated bands for MW comparison"
            txbox.text_frame.paragraphs[0].font.color.rgb = _GREY
            self._add_slide_number(slide)
            return

        headers = ["MW (kDa)"] + [sample_text(lane)[:20] for lane in self.data.lanes]
        rows = []
        for cluster in clusters:
            row = [f"{cluster['mw']:.1f}"]
            for lane_idx in range(len(self.data.lanes)):
                band = cluster["bands"].get(lane_idx)
                if band and band["pct_lane"] is not None:
                    row.append(f"{band['pct_lane']:.1f}%")
                else:
                    row.append("-")
            rows.append(row)

        page_size = self.rows_fitting(1.5)
        for offset in range(0, len(rows), page_size):
            slide = self._new_slide()
            page_rows = rows[offset : offset + page_size]
            title = "Band Comparison"
            if len(rows) > page_size:
                title += f" (Page {offset // page_size + 1})"
            self._add_header_bar(slide, title)
            self._add_data_table(slide, headers, page_rows)
            self._add_slide_number(slide)

    def _add_lane_detail_slides(self):
        """Add one slide per lane with summary and electropherogram."""
        from .comparison_builder import ComparisonReportBuilder

        for i, lane in enumerate(self.data.lanes):
            slide = self._new_slide()
            title = self._lane_title(i + 1, lane)
            self._add_header_bar(slide, title)

            # The lane in the sample identity card's look on the left, its facts and bands on the right: the
            # lane's fields, then its cells of its kind's readout columns (page_rows).
            kind = self.data.kind_of(lane)
            facts = [
                ("Source", lane.analysis_name[:30]),
                ("Assay", kind.label if kind else lane.gel_type),
                ("Lane #", str(lane.lane_number)),
                ("Condition", lane.condition or "N/A"),
            ]
            if kind is not None:
                facts += [
                    (column["label"], cell_text(lane, column["key"]) or "—")
                    for column in kind.columns
                    if column["key"] in lane.readout_cells and column["key"] != "bands"
                ]
            facts.append(("Bands", f"{lane.band_count} ({lane.poi_band_count} POI)" if lane.band_count else "N/A"))
            figure = self.safe_render(
                lambda lane=lane, kind=kind: self._render_lane_figure(lane, kind.readout if kind else ""),
                label=f"lane {i + 1}",
            )
            if figure is None:
                builder = ComparisonReportBuilder.__new__(ComparisonReportBuilder)
                builder.data = self.data
                figure = self.safe_render(
                    lambda lane=lane, i=i, builder=builder: builder._render_electropherogram(
                        lane, index=i, dark_theme=False
                    ),
                    label=f"lane {i + 1} electropherogram",
                )
            self.add_lane_panel(slide, title, lane, facts, figure)
            self._add_slide_number(slide)

    def _add_gel_table_slide(self):
        """Add combined slide with reconstructed gel image (left) and sample summary table (right)."""
        from .comparison_builder import ComparisonReportBuilder

        slide = self._new_slide()
        self._add_header_bar(slide, "Gel Overview & Sample Summary", height=0.8)

        # --- Left side: Reconstructed gel image ---
        builder = ComparisonReportBuilder.__new__(ComparisonReportBuilder)
        builder.data = self.data
        gel_buf = builder._render_reconstructed_gel(self.data.lanes, show_bands=self.band_overlay)

        # Layout: gel takes left ~55%, table takes right ~45%
        gel_left = 0.3
        gel_max_width = 6.8
        gel_max_height = 6.0
        table_left = 7.4
        table_width = 5.6

        if gel_buf:
            from PIL import Image as PILImage

            gel_buf.seek(0)
            img = PILImage.open(gel_buf)
            w, h = img.size
            aspect = w / h

            if aspect > gel_max_width / gel_max_height:
                display_w = gel_max_width
                display_h = display_w / aspect
            else:
                display_h = gel_max_height
                display_w = display_h * aspect

            gel_buf.seek(0)
            slide.shapes.add_picture(
                gel_buf,
                Inches(gel_left),
                Inches(1.0),
                Inches(display_w),
                Inches(display_h),
            )

        # --- Right side: Compact sample summary table: each lane's main value for its kind's readout ---
        headers = ["#", "Sample", "Assay", "Ln", "Value"]
        rows = []
        for i, lane in enumerate(self.data.lanes, 1):
            kind = self.data.kind_of(lane)
            sample = sample_text(lane)
            rows.append(
                [
                    str(i),
                    (sample[:18] + "..") if len(sample) > 20 else sample,
                    (kind.label[:24] if kind else "-"),  # "Western blot — anti-HCP" whole: cut, two assays read alike
                    str(lane.lane_number),
                    headline_text(kind.readout, lane) if kind else "-",
                ]
            )

        # The compact table, as many lanes as fit beside the gel (it kept the first 15).
        self._add_data_table(
            slide,
            headers,
            rows,
            top=1.0,
            left=table_left,
            width=table_width,
            max_rows=self.rows_fitting(1.0),
            font_size=8,
        )

        self._add_slide_number(slide)

    def _add_quantification_slide(self):
        """Per-analysis protein-quantification calibration summary slide.

        No shared curve / no re-fit — reads ``analysis_quant_summaries`` from the
        collector and renders a single table grouped by analysis_id.
        """
        data = self.data
        if not data.has_quantification or not data.analysis_quant_summaries:
            return

        slide = self._new_slide()
        self._add_header_bar(slide, "Protein Quantification")

        names = {}
        for lane in data.lanes:
            names.setdefault(lane.analysis_id, lane.analysis_name)

        headers = ["Analysis", "Method", "Unit", "Equation", "R²", "Quality"]
        rows = [
            [
                names.get(aid, aid),
                s["method"],
                s["unit"],
                s["equation"],
                f"{s['r_squared']:.4f}",
                s["r_squared_quality"],
            ]
            for aid, s in data.analysis_quant_summaries.items()
        ]
        self._add_data_table(slide, headers, rows)
        self._add_slide_number(slide)

    def _add_materials_methods_slide(self):
        from .constants import METHODOLOGY_CALIBRATION, METHODOLOGY_DENSITOMETRY

        methods = [("Densitometry Analysis", METHODOLOGY_DENSITOMETRY)]
        if self.data.calibrated_count > 0:
            methods.append(("MW Calibration", METHODOLOGY_CALIBRATION))
        # What the lane values mean, for each readout the compared assays are read for.
        for readout in dict.fromkeys(kind.readout for kind in self.data.kinds):
            if readout in READOUT_METHODOLOGY:
                methods.append(READOUT_METHODOLOGY[readout])

        # Three methods per slide: a fourth ran past the foot of the slide.
        for offset in range(0, len(methods), 3):
            slide = self._new_slide()
            self._add_header_bar(slide, "Materials & Methods" + (" (continued)" if offset else ""))
            y = 1.5
            for title, text in methods[offset : offset + 3]:
                # Section title
                txbox = slide.shapes.add_textbox(
                    Inches(0.5),
                    Inches(y),
                    Inches(12),
                    Inches(0.35),
                )
                p = txbox.text_frame.paragraphs[0]
                p.text = title
                p.font.size = Pt(13)
                p.font.bold = True
                p.font.color.rgb = _ACCENT
                p.font.name = HEADING_FONT
                y += 0.4

                # Body
                txbox = slide.shapes.add_textbox(
                    Inches(0.5),
                    Inches(y),
                    Inches(12),
                    Inches(1.5),
                )
                tf = txbox.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = text.strip()
                p.font.size = Pt(10)
                p.font.color.rgb = _DARK
                p.font.name = BODY_FONT
                y += 1.7

            self._add_slide_number(slide)

    # ── Image rendering helpers ───────────────────────────────────

    def _render_gel_variant(self, gel_image_id, lanes, variant, readout, ticks) -> BytesIO | None:
        """One analysis's compared lanes on its gel, in the whole-gel look (``gel_figure.render_gel_figure``), or None
        without its image."""
        image_file = self._gel_image_file(gel_image_id)
        if image_file is None:
            return None
        from .gel_figure import render_gel_figure

        return render_gel_figure(image_file, lanes, variant=variant, readout=readout, ticks=ticks)

    def _render_lane_figure(self, lane, readout) -> BytesIO | None:
        """The lane in the identity card's look (``gel_figure.render_lane_figure``) on its own gel, or None without its
        card entry or its gel image."""
        entry = self.data.strips.get(lane.lane_id)
        image_file = self._gel_image_file(lane.gel_image_id)
        if entry is None or image_file is None:
            return None
        from .gel_figure import render_lane_figure

        return render_lane_figure(image_file, entry, lane, readout=readout)

    @staticmethod
    def _gel_image_file(gel_image_id):
        """The gel image's display file, else its original, else None."""
        if not gel_image_id:
            return None
        from gel_analyzer.models import GelImage

        gel_image = GelImage.objects.get(pk=gel_image_id)
        return gel_image.display_file or gel_image.original_file or None

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> BytesIO:
        """Build the complete PowerPoint presentation and return as BytesIO."""
        logger.info(f"Building Lane Comparison PPTX report for '{self.data.name}'")

        # Title slide always included
        try:
            self._add_title_slide()
        except Exception as e:
            logger.error(f"Failed to add title slide: {e}")

        slide_map = [
            ("overview", self._add_overview_slide, "overview"),
            ("sample_summary", self._add_sample_summary_slides, "sample summary"),
            ("gel_images", self._add_gel_table_slide, "gel overview & table"),
            ("gel_images", self._add_gel_variant_slides, "gel image variants"),
            ("digital_gel", self._add_digital_gel_slide, "digital gel"),
            ("poi_purity", self._add_poi_purity_slide, "POI purity"),
            ("band_comparison", self._add_band_comparison_slides, "band comparison"),
            ("lane_details", self._add_lane_detail_slides, "lane details"),
            ("quantification", self._add_quantification_slide, "quantification"),
            ("materials_methods", self._add_materials_methods_slide, "materials & methods"),
        ]

        for key, method, desc in slide_map:
            if self._should_include(key):
                try:
                    method()
                except Exception as e:
                    logger.error(f"Failed to add PPTX slide '{desc}': {e}")

        buf = BytesIO()
        self.prs.save(buf)
        buf.seek(0)

        logger.info(f"Lane Comparison PPTX report built for '{self.data.name}'")
        return buf
