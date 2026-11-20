"""
PowerPoint builder for densitometry analysis reports.

Generates 16:9 .pptx presentations with Phoresis branding (accent blue,
Inter typography) using python-pptx. Palette tokens come from
``services.report.constants``.
"""

from io import BytesIO

from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from phoresis_core.logging_config import get_logger

from .constants import (
    BAND_PALETTE_HEX,
    BODY_FONT,
    GEL_VARIANT_TITLES,
    GEL_VARIANTS_CANONICAL_ORDER,
    GEL_VARIANTS_DEFAULT,
    HEADING_FONT,
    METHODOLOGY_CALIBRATION,
    METHODOLOGY_DENSITOMETRY,
    METHODOLOGY_QUANTIFICATION,
    MUTED_GRAY,
    PHORESIS_ACCENT,
    PHORESIS_INK,
    READOUT_METHODOLOGY,
    calibration_range_display,
    is_outside_calibration_range,
)
from .densitometry_data_collector import DensitometryReportData
from .digital_gel import render_digital_gel
from .page_rows import cell_text, sample_text
from .pptx_base import BasePptxReportBuilder

logger = get_logger(__name__)

# Brand palette (the comparison deck's own), from constants.py
_ACCENT = RGBColor(*PHORESIS_ACCENT)
_DARK = RGBColor(*PHORESIS_INK)
_GREY = RGBColor(*MUTED_GRAY)

# Under the digital gel: what its amber dot and its placement mean (digital_gel.py).
DIGITAL_GEL_CAPTION = (
    "Amber dot: a lane whose bands have no MW. Unless every band has an MW, each band sits at its position on its "
    "gel, and the kDa labels are the ladder's markers."
)

# Sections not applicable to PowerPoint
_PPTX_SKIP_SECTIONS = set()  # All sections can produce slides


class DensitometryPowerPointBuilder(BasePptxReportBuilder):
    """
    Densitometry Analysis PowerPoint report — thin subclass of
    BasePptxReportBuilder. Slides are built on the neutral 16:9 deck's layouts
    (cover/section/title_text/title_chart/image_wide: pptx_base.LAYOUTS) via
    new_slide()/set_title(), not hand-drawn bars.
    """

    def __init__(
        self,
        data: DensitometryReportData,
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
        self.set_title(slide, "Densitometry Analysis Report")
        # The analysis, then what the gel is read for and where the analysis stands, as the page's header says.
        self.set_subtitle(
            slide, f"{self.data.analysis_name or ''}\n{self.data.assay_label} · {self.data.analysis_status}"
        )

        # Keep the key facts (previously printed on the cover) as speaker notes
        # so the cover stays clean/native; the Overview slide lists them too.
        avg_purity_str = self.data.average_purity_text
        self.add_speaker_notes(
            slide,
            f"Gel Type: {self.data.gel_type}  |  Lanes: {self.data.total_lanes_count}  |  "
            f"Bands: {self.data.total_bands_count}  |  Avg Purity: {avg_purity_str}\n"
            f"Status: {self.data.analysis_status}  |  Analyst: {self.data.created_by_name}  |  "
            f"{self.data.created_at}\n"
            f"Report generated: {self.data.report_generated_at}  |  By: {self.data.report_generated_by}",
        )

    def _add_overview_slide(self):
        """The analysis page's summary: its metric cards, its "To check" items, and the analysis's facts beside them
        (page_rows: the page's own cards and checks -- the deck once said nothing of a saturated band or a lane
        without its POI band)."""
        slide = self._new_slide()
        self._add_header_bar(slide, "Analysis Overview")
        self.add_cards(slide, self.data.cards, top=1.35)
        self.add_checks(slide, self.data.checks, left=0.5, top=2.65, width=7.7)
        calibration = self.data.calibrations[0] if self.data.calibrations else None
        quant = self.data.quant_calibration
        self.add_facts(
            slide,
            [
                ("Assay", self.data.assay_label),
                ("Gel type", self.data.gel_type),
                ("Image", self.data.image_title),
                (
                    "Status",
                    self.data.analysis_status + (f" — {self.data.status_hint}" if self.data.status_hint else ""),
                ),
                ("Analyst", self.data.created_by_name),
                ("Created", self.data.created_at),
                ("Densitometry", self.data.densitometry_computed_at or "not run"),
                (
                    "MW calibration",
                    f"{calibration.template_name} (R² {calibration.r_squared:.3f})" if calibration else "None",
                ),
                ("Quantification", f"{quant.method}, R² {quant.r_squared:.3f}" if quant else "None"),
            ],
            left=8.5,
            top=2.65,
            width=4.33,
        )
        self._add_slide_number(slide)

    def _lane_title(self, lane) -> str:
        """``Lane <n>: <sample>``, the HCP reference lane saying so."""
        title = f"Lane {lane.lane_number}: {sample_text(lane)}"
        return f"{title} (reference)" if lane.is_reference else title

    def _add_sample_summary_slides(self):
        # The lane's own fields, then the readout's columns with the analysis page's cells (page_rows).
        columns = self.data.readout_columns
        headers = ["Lane", "Sample", "Type", "Condition", "Load (µg)"] + [column["label"] for column in columns]
        # The page's saturation check, lane by lane: a column only on a gel that has a saturated band.
        flagged = any(lane.saturated_bands for lane in self.data.lanes)
        if flagged:
            headers.append("Saturated")
        rows = []
        for lane in self.data.lanes:
            load_str = ""
            if lane.protein_load_ug is not None:
                load_str = f"{lane.protein_load_ug:.1f}"
            rows.append(
                [
                    str(lane.lane_number),
                    sample_text(lane) + (" (REF)" if lane.is_reference else ""),
                    lane.lane_type,
                    lane.condition or "-",
                    load_str,
                ]
                + [cell_text(lane, column["key"]) for column in columns]
                + (["⚠ " + ", ".join(lane.saturated_bands) if lane.saturated_bands else ""] if flagged else [])
            )

        # Condition and load only where a lane has one; as many rows a slide as fit.
        headers, rows = self.drop_empty_columns(headers, rows, {"Condition", "Load (µg)"})
        page_size = self.rows_fitting(1.5)
        for offset in range(0, len(rows), page_size):
            slide = self._new_slide()
            page_rows = rows[offset : offset + page_size]
            page_num = offset // page_size + 1
            title = "Sample Summary"
            if len(rows) > page_size:
                title += f" (Page {page_num})"
            self._add_header_bar(slide, title)
            self._add_data_table(slide, headers, page_rows)
            self._add_slide_number(slide)

    def _add_gel_variant_slides(self):
        """The SELECTED gel-image variants, one slide each (spec D3), in the whole-gel look of the app's "Full gel" tile
        (gel_figure): the photo with every lane outlined, above each lane its number and sample, under it the page's
        value, the ladder's kDa on the left; the legend in the text area beside. LANES_ONLY draws no band, FULL every
        band by its type, KEY_BANDS the bands the readout is read from (on a western, by their role). Canonical order
        LANES_ONLY -> KEY_BANDS -> FULL; default ["FULL"]."""
        from .gel_figure import legend_lines
        from .gel_overlay import GelOverlayVariant

        saturated = any(band.saturated for lane in self.data.lanes for band in lane.bands)
        for label in self.gel_variants:
            variant = GelOverlayVariant(label)
            picture = self.safe_render(lambda v=variant: self._render_gel_variant(v), label=f"gel image {label}")
            self.add_figure_slide(
                f"Gel image — {GEL_VARIANT_TITLES[label]}",
                picture,
                legend_lines(variant, self.data.readout, has_ticks=bool(self.data.mw_ticks), has_saturated=saturated),
                placeholder_label=f"Gel image ({GEL_VARIANT_TITLES[label]})",
            )
            self.slide_number += 1

    def _add_digital_gel_slide(self):
        """Add digital gel slide (all lanes)."""
        slide = self._new_slide()
        self._add_header_bar(slide, "Digital Gel (All Lanes)")

        # Render digital gel
        digital_buf = self._render_digital_gel(self.data.lanes)

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
        """The chart of the gel's readout (readout_chart): purity, HMWS / main band / LMWS or HCP % of reference;
        no slide on a gel that measures nothing."""
        from .readout_chart import chart_title, render_readout_chart

        title = chart_title(self.data.readout, self.data.lanes)
        if title is None:
            return
        slide = self._new_slide()
        self._add_header_bar(slide, title)

        mean = None
        if self.data.average_purity is not None:
            mean = (self.data.average_purity, f"Mean {self.data.average_purity_text}")
        chart_buf = render_readout_chart(
            self.data.readout, self.data.lanes, mean=mean, figsize=(10, 4.5), dpi=150, dark_theme=False
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

    def _add_lane_detail_slides(self):
        """One slide per lane but a ladder or an empty one, in the sample identity card's look (gel_figure): the lane
        put forward on its whole gel, its bands named, its profile beside on the same rows, the ladder's kDa; its facts
        and its band table on the right. Without its card entry or its image, the electropherogram as before."""
        sample_lanes = [lane for lane in self.data.lanes if lane.lane_type_code not in ("LADDER", "EMPTY")]

        for lane in sample_lanes:
            slide = self._new_slide()
            title = self._lane_title(lane)
            self._add_header_bar(slide, title)
            facts = [
                ("Sample", sample_text(lane)),
                ("Type", lane.lane_type),
                ("Condition", lane.condition or "N/A"),
            ]
            facts += [
                (column["label"], cell_text(lane, column["key"]) or "—")
                for column in self.data.readout_columns
                if column["key"] in lane.readout_cells
            ]
            figure = self.safe_render(
                lambda lane=lane: self._render_lane_figure(lane), label=f"lane {lane.lane_number}"
            )
            if figure is None:
                figure = self.safe_render(
                    lambda lane=lane: self._render_electropherogram(lane), label=f"lane {lane.lane_number} profile"
                )
            self.add_lane_panel(slide, title, lane, facts, figure)
            self._add_slide_number(slide)

    def _render_lane_figure(self, lane) -> BytesIO | None:
        """The lane in the identity card's look (``gel_figure.render_lane_figure``), or None without its card entry or
        its gel image."""
        entry = self.data.strips.get(lane.lane_id)
        if entry is None or not self.data.gel_image_id:
            return None
        from gel_analyzer.models import GelImage

        from .gel_figure import render_lane_figure

        gel_image = GelImage.objects.get(pk=self.data.gel_image_id)
        image_file = gel_image.display_file or gel_image.original_file
        if not image_file:
            return None
        return render_lane_figure(image_file, entry, lane, readout=self.data.readout)

    def _add_terrain_view_slides(self):
        """The 3D terrain of every lane but a ladder or an empty one, four lanes a slide (owner, 2026-10-13: one a
        slide made nine slides a deck)."""
        from .terrain_chart import render_terrain_chart

        lanes = [lane for lane in self.data.lanes if lane.lane_type_code not in ("LADDER", "EMPTY")]
        cell_w, cell_h = 6.1, 2.6
        for offset in range(0, len(lanes), 4):
            group = lanes[offset : offset + 4]
            slide = self._new_slide()
            numbers = ", ".join(str(lane.lane_number) for lane in group)
            self._add_header_bar(slide, f"3D Terrain — lane{'s' if len(group) > 1 else ''} {numbers}")
            for k, lane in enumerate(group):
                left, top = 0.5 + (k % 2) * (cell_w + 0.13), 1.35 + (k // 2) * (cell_h + 0.15)
                chart_buf = self.safe_render(
                    lambda lane=lane: render_terrain_chart(lane, figsize=(6.1, 2.6), dpi=150, dark_theme=False),
                    label=f"terrain lane {lane.lane_number}",
                )
                if chart_buf:
                    self.add_picture_fit(
                        slide, chart_buf, left=left, top=top, max_width=cell_w, max_height=cell_h, center=True
                    )
                else:
                    self.add_render_placeholder(
                        slide, f"3D terrain of lane {lane.lane_number}", left=left, top=top + 1.0, width=cell_w
                    )
            self._add_slide_number(slide)

    def _add_materials_methods_slide(self):
        slide = self._new_slide()
        self._add_header_bar(slide, "Materials & Methods")

        methods = [("Densitometry Analysis", METHODOLOGY_DENSITOMETRY)]
        if self.data.has_calibration:
            methods.append(("MW Calibration", METHODOLOGY_CALIBRATION))
        # What the lane values mean, for the readout the gel is read for.
        if self.data.readout in READOUT_METHODOLOGY:
            methods.append(READOUT_METHODOLOGY[self.data.readout])

        y = 1.5
        for title, text in methods:
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

    def _render_gel_variant(self, variant) -> BytesIO | None:
        """The gel in the whole-gel look (``gel_figure.render_gel_figure``), or None without its image."""
        if not self.data.gel_image_id:
            return None
        from gel_analyzer.models import GelImage

        from .gel_figure import render_gel_figure

        gel_image = GelImage.objects.get(pk=self.data.gel_image_id)
        image_file = gel_image.display_file or gel_image.original_file
        if not image_file:
            return None
        return render_gel_figure(
            image_file, self.data.lanes, variant=variant, readout=self.data.readout, ticks=self.data.mw_ticks
        )

    def _render_digital_gel(self, lanes) -> BytesIO | None:
        """Delegate to the shared renderer (fixes inverted axis, POI colour,
        and the old return-None-on-uncalibrated bug)."""
        return render_digital_gel(lanes, calibration=None, footer_field="lane_type")

    def _render_electropherogram(self, lane) -> BytesIO | None:
        """
        Render a single-lane electropherogram with matplotlib.

        Args:
            lane: LaneReportData with profile_data

        Returns:
            BytesIO with PNG image, or None
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        if not lane.profile_data:
            return None

        profile = lane.profile_data
        intensities = np.array(profile.get("intensities", []), dtype=float)
        y_positions = np.array(profile.get("y_positions", []), dtype=float)

        if len(intensities) < 2 or len(y_positions) < 2:
            return None

        try:
            PEAK_COLORS = {
                "Protein of Interest": BAND_PALETTE_HEX["POI"],  # #A855F7 purple
                "Other": BAND_PALETTE_HEX["OTHER"],  # #22C55E green (spec §5)
                "MW Reference": BAND_PALETTE_HEX["MW_REFERENCE"],  # #F97316 orange
                "MW Ladder": BAND_PALETTE_HEX["MW_REFERENCE"],  # #F97316 orange
                "Calibration Point": BAND_PALETTE_HEX.get("CALIBRATION", "#F87171"),
            }

            # --- Determine X-axis data ---
            mw_values = profile.get("mw_values")
            has_mw = mw_values and any(v is not None and v > 0 for v in mw_values)

            if has_mw:
                # Filter out None/zero MW values and pair with intensities
                paired = [
                    (mw, inten) for mw, inten in zip(mw_values, intensities, strict=False) if mw is not None and mw > 0
                ]
                if not paired:
                    has_mw = False

            if has_mw:
                x_values = np.array([p[0] for p in paired])
                y_values = np.array([p[1] for p in paired])
                x_label = "Molecular Weight (kDa)"
                use_log_x = True
            else:
                x_values = y_positions
                y_values = intensities
                x_label = "Y Position (pixels)"
                use_log_x = False

            if len(x_values) < 2:
                return None

            # --- Create figure with light theme (for PowerPoint) ---
            fig, ax = plt.subplots(figsize=(7, 2.5), dpi=200)
            fig.patch.set_facecolor("#ffffff")
            ax.set_facecolor("#ffffff")

            # Profile line
            hex_color = "#3B82F6"  # blue
            ax.plot(x_values, y_values, color=hex_color, linewidth=1.5, zorder=3)

            # Area fill under curve
            ax.fill_between(x_values, 0, y_values, color=hex_color, alpha=0.2, zorder=2)

            # Log scale for MW axis
            if use_log_x:
                ax.set_xscale("log")
                ax.invert_xaxis()  # High MW on left
                from matplotlib.ticker import ScalarFormatter

                ax.xaxis.set_major_formatter(ScalarFormatter())
                ax.xaxis.get_major_formatter().set_scientific(False)

            # --- Peak markers at band positions ---
            for band in lane.bands:
                # Determine x position for this band
                if has_mw and band.estimated_mw_kda and band.estimated_mw_kda > 0:
                    bx = band.estimated_mw_kda
                elif band.position_y is not None and not has_mw:
                    bx = float(band.position_y)
                else:
                    continue

                # Find closest intensity value
                idx = np.argmin(np.abs(x_values - bx))
                by = y_values[idx]

                peak_color = PEAK_COLORS.get(band.band_type, "#9E9E9E")
                ax.plot(
                    bx, by, "o", color=peak_color, markersize=6, markeredgecolor="white", markeredgewidth=1.5, zorder=5
                )

                # MW label above peak
                if band.estimated_mw_kda:
                    ax.annotate(
                        f"{band.estimated_mw_kda:.0f} kDa",
                        (bx, by),
                        textcoords="offset points",
                        xytext=(0, 10),
                        fontsize=7,
                        color="#333333",
                        fontweight="bold",
                        ha="center",
                        zorder=6,
                    )

            # --- Axis styling (light theme) ---
            ax.set_xlabel(x_label, color="#333333", fontsize=9)
            ax.set_ylabel("Intensity", color="#333333", fontsize=9)
            ax.tick_params(colors="#333333", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#cccccc")
            ax.set_ylim(bottom=0)

            # Title with sample name
            ax.set_title(
                f"{sample_text(lane)} (L{lane.lane_number})", color="#333333", fontsize=10, fontweight="bold", pad=8
            )

            fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.18)
            buf = BytesIO()
            fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return buf

        except Exception as e:
            logger.warning(f"Failed to render electropherogram: {e}")
            return None

    # ── Protein quantification ────────────────────────────────────

    def _qsd_add_table(self, slide, headers, rows, *, top_in, highlight_rows=None):
        """The quantification tables: the compact table across the slide, out-of-spec rows filled light red."""
        return self._add_data_table(slide, headers, rows, top=top_in, highlight_rows=highlight_rows or ())

    def _calibration_curve_series(self):
        """Build the XY_SCATTER series list for the base ``add_xy_scatter``.

        Returns ``[(name, [(x, y), ...]), ...]`` for: calibration points,
        excluded points (faded — separate series), the fit line as a sampled
        polyline series (spec C4 — no combo charts), and control points.
        Pure data; no chart objects.
        """
        import numpy as np

        from gel_analyzer.models import ProteinQuantCalibration
        from gel_analyzer.services.quantification.models import QuantParams, QuantResult
        from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

        data = self.data
        series: list[tuple] = []

        inc = [
            (p.corrected_area, p.load_amount)
            for p in data.quant_points
            if not p.is_excluded and p.corrected_area is not None and p.load_amount is not None
        ]
        exc = [
            (p.corrected_area, p.load_amount)
            for p in data.quant_points
            if p.is_excluded and p.corrected_area is not None and p.load_amount is not None
        ]

        if inc:
            series.append(("Calibration", inc))
        if exc:
            series.append(("Excluded", exc))

        # Fit line — read-only re-projection sampled across the calibration
        # x-range (markers turned off on the rendered series below).
        if len(inc) >= 2:
            calib = ProteinQuantCalibration.objects.filter(analysis_id=data.analysis_id, is_active=True).first()
            if calib:
                svc = ProteinQuantCalibrationService(QuantParams(method=calib.method, unit=calib.unit))
                fit_result = QuantResult(
                    success=True,
                    method=calib.method,
                    unit=calib.unit,
                    coefficients=calib.coefficients,
                    r_squared=calib.r_squared,
                    equation=calib.equation,
                )
                xs = list(np.linspace(min(x for x, _ in inc), max(x for x, _ in inc), 50))
                fit_pts = []
                for x in xs:
                    y = svc.project(float(x), fit_result)
                    if y is not None:
                        fit_pts.append((float(x), float(y)))
                if fit_pts:
                    series.append(("Fit", fit_pts))

        # Control points (known vs predicted)
        ctrl_pts = [
            (c.known_amount, c.predicted_amount)
            for c in data.quant_controls
            if c.known_amount is not None and c.predicted_amount is not None
        ]
        if ctrl_pts:
            series.append(("Controls", ctrl_pts))

        return series

    def _add_calibration_curve_chart(self, slide):
        """Native XY_SCATTER calibration curve under the slide's title.

        Uses the base ``add_xy_scatter`` (the chart is a shape in the
        'title_chart' slide's CHART_BOX). Turns markers off on the Fit
        series so it reads as a line. Returns the chart, or None when there
        is nothing to plot (caller draws a visible placeholder).
        """
        data = self.data
        if not data.quant_points:
            return None
        series = self._calibration_curve_series()
        if not series:
            return None

        unit = data.quant_calibration.unit if data.quant_calibration else ""
        chart = self.add_xy_scatter(
            slide,
            series=series,
            x_title="Corrected area",
            y_title=f"Amount ({unit})" if unit else "Amount",
        )
        if chart is None:
            return None

        chart.has_title = True
        chart.chart_title.text_frame.text = "Calibration curve"

        # Fit series → markers off (best-effort; never fail the slide).
        try:
            from pptx.oxml.ns import qn

            for plot in chart.plots:
                for s in plot.series:
                    if s.name == "Fit":
                        ser = s._element
                        marker = ser.makeelement(qn("c:marker"), {})
                        symbol = marker.makeelement(qn("c:symbol"), {"val": "none"})
                        marker.append(symbol)
                        ser.append(marker)
        except Exception:
            pass

        return chart

    def _add_quantification_slides(self):
        """PPTX: methodology slide + curve slide + Table A/B/C slides."""
        data = self.data
        if not data.has_quantification or data.quant_calibration is None:
            return
        cal = data.quant_calibration

        # Methodology slide
        slide = self._new_slide()
        self._add_header_bar(slide, "Protein Quantification")
        tb = slide.shapes.add_textbox(Inches(0.6), Inches(1.2), Inches(12.0), Inches(5.8))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.text = METHODOLOGY_QUANTIFICATION.strip()
        for line in [
            f"Method: {cal.method}",
            f"Unit: {cal.unit}",
            f"Equation: {cal.equation}",
            f"R²: {cal.r_squared:.4f} ({cal.r_squared_quality})",
            f"Points used / excluded: {cal.n_points} / {cal.n_excluded}",
            f"Fitted by: {cal.created_by_name} on {cal.created_at}",
            "Recovery in-spec range: 80–120%",
        ] + ([f"Note: fit auto-recomputed (drift) at {cal.last_recomputed_at}"] if cal.last_recomputed_at else []):
            p = tf.add_paragraph()
            p.text = line
            p.font.size = Pt(12)

        if not data.quant_points:
            return

        # Curve slide — 'title_chart' layout, a native XY_SCATTER drawn under the
        # title via the base add_xy_scatter (spec C4). Falls back gracefully
        # (safe_render) if the chart cannot be drawn.
        curve_slide = self._new_slide("title_chart")
        self._add_header_bar(curve_slide, "Calibration Curve")
        chart = self.safe_render(
            lambda: self._add_calibration_curve_chart(curve_slide),
            label="calibration curve chart",
        )
        if chart is None:
            self.add_render_placeholder(curve_slide, "Calibration curve", top=3.0)

        # Table A — calibration points
        a_slide = self._new_slide()
        self._add_header_bar(a_slide, "Calibration Points")
        headers_a = ["Lane #", "Load", "Unit", "Corrected area", "Residual %", "Excluded"]
        rows_a = [
            [
                p.lane_number,
                f"{p.load_amount:.3g}" if p.load_amount is not None else "—",
                p.load_unit or "",
                f"{p.corrected_area:.1f}" if p.corrected_area is not None else "—",
                f"{p.residual_pct:.2f}" if p.residual_pct is not None else "—",
                "Yes" if p.is_excluded else "",
            ]
            for p in data.quant_points
        ]
        self._qsd_add_table(a_slide, headers_a, rows_a, top_in=1.4)

        # Table B — controls / QC (omit if none; red fill on out-of-spec)
        if data.quant_controls:
            b_slide = self._new_slide()
            self._add_header_bar(b_slide, "Controls / QC Recovery")
            headers_b = ["Lane #", "Known", "Predicted", "Recovery %", "Range", "Flag"]
            rows_b = [
                [
                    c.lane_number,
                    f"{c.known_amount:.3g}" if c.known_amount is not None else "—",
                    f"{c.predicted_amount:.3g}" if c.predicted_amount is not None else "—",
                    f"{c.recovery_pct:.2f}" if c.recovery_pct is not None else "—",
                    calibration_range_display(c.calibration_range),
                    "OUT OF SPEC" if c.out_of_spec else "OK",
                ]
                for c in data.quant_controls
            ]
            self._qsd_add_table(
                b_slide,
                headers_b,
                rows_b,
                top_in=1.4,
                highlight_rows=[i for i, c in enumerate(data.quant_controls) if c.out_of_spec],
            )

        # Table C — sample estimated amounts
        if data.quant_samples:
            c_slide = self._new_slide()
            self._add_header_bar(c_slide, "Sample Estimated Amounts")
            headers_c = ["Lane #", "Sample", "Est. amount", "Unit", "Range"]
            rows_c = [
                [
                    s.lane_number,
                    s.sample_name or "—",
                    f"{s.estimated_amount:.3g}" if s.estimated_amount is not None else "N/A",
                    s.unit or "",
                    calibration_range_display(s.calibration_range),
                ]
                for s in data.quant_samples
            ]
            self._qsd_add_table(
                c_slide,
                headers_c,
                rows_c,
                top_in=1.4,
                highlight_rows=[
                    i for i, s in enumerate(data.quant_samples) if is_outside_calibration_range(s.calibration_range)
                ],
            )

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> BytesIO:
        """Build the complete PowerPoint presentation and return as BytesIO."""
        logger.info(f"Building Densitometry PPTX report for '{self.data.analysis_name}'")

        # Title slide always included
        try:
            self._add_title_slide()
        except Exception as e:
            logger.error(f"Failed to add title slide: {e}")

        slide_map = [
            ("overview", self._add_overview_slide, "overview"),
            ("sample_summary", self._add_sample_summary_slides, "sample summary"),
            ("gel_image", self._add_gel_variant_slides, "gel image variants"),
            ("digital_gel", self._add_digital_gel_slide, "digital gel"),
            ("poi_purity", self._add_poi_purity_slide, "POI purity"),
            ("lane_details", self._add_lane_detail_slides, "lane details"),
            ("quantification", self._add_quantification_slides, "quantification"),
            ("terrain_view", self._add_terrain_view_slides, "terrain view"),
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

        logger.info(f"Densitometry PPTX report built for '{self.data.analysis_name}'")
        return buf
