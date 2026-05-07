"""
Word document builder for densitometry analysis reports.

Generates comprehensive analysis reports with the Phoresis brand
palette (accent-600 blue, Inter), server-side rendered gel images,
digital gel visualization, electropherograms, 3D terrain views, and
detailed lane analysis.
"""

from io import BytesIO
from pathlib import Path

from docx.shared import Inches

from phoresis_core.logging_config import get_logger

from .builder import BaseReportBuilder
from .constants import (
    HEADING_FONT,
    IMAGE_FULL_WIDTH,
    METHODOLOGY_CALIBRATION,
    METHODOLOGY_DENSITOMETRY,
    METHODOLOGY_PURITY,
    MUTED_GRAY,
    PHORESIS_ACCENT,
    PHORESIS_LOGO_PATH,
    SMALL_SIZE,
    TITLE_SIZE,
)
from .densitometry_data_collector import DensitometryReportData

logger = get_logger(__name__)


class DensitometryReportBuilder(BaseReportBuilder):
    """
    Generates comprehensive Word document for Densitometry Analysis reports
    using python-docx with the Phoresis brand palette.

    All visuals are rendered server-side with Pillow/matplotlib.
    Rendering methods (_render_*) have no dependency on self.document
    so they can be reused by PPTX builder via the __new__ trick.
    """

    def __init__(
        self,
        data: DensitometryReportData,
        sections: list[str] | None = None,
        band_overlay: bool = True,
    ):
        """
        Initialize the densitometry report builder.

        Args:
            data: DensitometryReportData instance with all structured report data
            sections: List of section keys to include, or None for all sections
            band_overlay: Whether to draw band overlay rectangles on gel images
        """
        self.data = data
        self.sections = sections
        self.band_overlay = band_overlay
        self.images = {}  # kept for BaseReportBuilder compatibility
        super().__init__()

    def _should_include(self, section_key: str) -> bool:
        """Check if a section should be included in the report."""
        if self.sections is None:
            return True
        return section_key in self.sections

    # ══════════════════════════════════════════════════════════════════
    # Rendering methods (no dependency on self.document)
    # ══════════════════════════════════════════════════════════════════

    def _render_full_gel_image(self, show_bands: bool = False) -> BytesIO | None:
        """
        Load the full gel image from the database and optionally draw the
        lane/band overlay matching the live web app.

        Delegates to ``gel_overlay.render_gel_overlay`` so the visual
        is shared with comparison + analysis builders.

        Args:
            show_bands: If True, draw the band layer too. When False,
                only the lane outlines are drawn (useful for the bare
                "full gel" section).

        Returns:
            BytesIO with PNG image, or None if image not available.
        """
        from gel_analyzer.models import GelImage

        from .gel_overlay import render_gel_overlay

        if not self.data.gel_image_id:
            return None

        try:
            gel_image = GelImage.objects.get(pk=self.data.gel_image_id)
            image_file = gel_image.display_file or gel_image.original_file
            if not image_file:
                return None
            return render_gel_overlay(
                image_file,
                self.data.lanes if self.data.lanes else [],
                draw_band_overlay=show_bands,
            )
        except Exception as e:
            logger.warning(f"Failed to render full gel image: {e}", exc_info=True)
            return None

    def _render_digital_gel(self, lanes) -> BytesIO | None:
        """
        Render a side-by-side digital gel image with Pillow for all lanes.

        Creates a single image with all lanes as vertical columns,
        bands positioned on a log10 MW scale, and a shared MW scale on the right.

        Args:
            lanes: list of LaneReportData

        Returns:
            BytesIO with PNG image, or None on failure
        """
        import math

        from PIL import Image, ImageDraw, ImageFont

        if not lanes:
            return None

        # Layout constants
        LANE_WIDTH = 100
        LANE_GAP = 6
        HEADER_HEIGHT = 36
        BODY_HEIGHT = 400
        FOOTER_HEIGHT = 24
        MW_SCALE_WIDTH = 70
        BAND_HEIGHT = 8
        BAND_INSET = int(LANE_WIDTH * 0.10)
        ACCENT_BAR_HEIGHT = 4

        # Colors
        BG_COLOR = (30, 30, 34)
        LANE_BG = (42, 42, 46)
        HEADER_BG = (26, 26, 30)
        TEXT_COLOR = (230, 230, 230)
        TEXT_DIM = (160, 160, 160)
        SCALE_LINE = (80, 80, 85)

        from .constants import BAND_PALETTE

        def _band_rgb(b):
            return BAND_PALETTE.get((b.band_type_code or "OTHER").upper(), BAND_PALETTE["OTHER"])["stroke"][:3]

        LANE_ACCENT_COLORS = [
            (59, 130, 246),
            (168, 85, 247),
            (34, 197, 94),
            (249, 115, 22),
            (236, 72, 153),
            (20, 184, 166),
            (245, 158, 11),
            (99, 102, 241),
        ]

        STANDARD_MWS = [10, 15, 20, 25, 37, 50, 75, 100, 150, 250]

        # Compute global MW range
        all_mws = []
        for lane in lanes:
            for band in lane.bands:
                if band.estimated_mw_kda and band.estimated_mw_kda > 0:
                    all_mws.append(band.estimated_mw_kda)

        has_mw = len(all_mws) > 0
        if has_mw:
            mw_min_raw = min(all_mws)
            mw_max_raw = max(all_mws)
            log_min = math.log10(mw_min_raw)
            log_max = math.log10(mw_max_raw)
            log_range = log_max - log_min
            if log_range < 0.1:
                log_range = 0.5
            log_min -= log_range * 0.10
            log_max += log_range * 0.10
            mw_min = 10**log_min
            mw_max = 10**log_max
        else:
            mw_min = 10
            mw_max = 250

        log_min = math.log10(mw_min)
        log_max = math.log10(mw_max)
        log_span = log_max - log_min
        if log_span <= 0:
            log_span = 1.0

        # Image dimensions
        n_lanes = len(lanes)
        total_width = LANE_GAP + n_lanes * (LANE_WIDTH + LANE_GAP) + MW_SCALE_WIDTH
        total_height = HEADER_HEIGHT + BODY_HEIGHT + FOOTER_HEIGHT

        img = Image.new("RGB", (total_width, total_height), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Fonts
        try:
            font = ImageFont.truetype("arial.ttf", 12)
            font_small = ImageFont.truetype("arial.ttf", 10)
            font_bold = ImageFont.truetype("arialbd.ttf", 12)
        except OSError:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
                font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
                font_bold = font
            except OSError:
                font = ImageFont.load_default()
                font_small = font
                font_bold = font

        def mw_to_y(mw_kda):
            log_mw = math.log10(max(mw_kda, 1))
            fraction = (log_max - log_mw) / log_span
            fraction = max(0.02, min(0.98, fraction))
            return HEADER_HEIGHT + int(fraction * BODY_HEIGHT)

        def position_to_y(pos_y, lane_height):
            fraction = pos_y / lane_height if lane_height and lane_height > 0 else 0.5
            fraction = max(0.02, min(0.98, fraction))
            return HEADER_HEIGHT + int(fraction * BODY_HEIGHT)

        # Draw each lane
        for i, lane in enumerate(lanes):
            col_x = LANE_GAP + i * (LANE_WIDTH + LANE_GAP)
            accent_color = LANE_ACCENT_COLORS[i % len(LANE_ACCENT_COLORS)]

            # Lane background
            draw.rectangle(
                [col_x, HEADER_HEIGHT, col_x + LANE_WIDTH, HEADER_HEIGHT + BODY_HEIGHT],
                fill=LANE_BG,
            )

            # Header
            draw.rectangle([col_x, 0, col_x + LANE_WIDTH, HEADER_HEIGHT], fill=HEADER_BG)
            draw.rectangle([col_x, 0, col_x + LANE_WIDTH, ACCENT_BAR_HEIGHT], fill=accent_color)

            # Header text
            label = lane.sample_name[:14] if lane.sample_name else f"Lane {lane.lane_number}"
            lbl_bbox = draw.textbbox((0, 0), label, font=font_small)
            lbl_w = lbl_bbox[2] - lbl_bbox[0]
            lbl_x = col_x + (LANE_WIDTH - lbl_w) // 2
            lbl_y = ACCENT_BAR_HEIGHT + 4
            draw.text((lbl_x, lbl_y), label, fill=TEXT_COLOR, font=font_small)

            ln_label = f"L{lane.lane_number}"
            ln_bbox = draw.textbbox((0, 0), ln_label, font=font_small)
            ln_w = ln_bbox[2] - ln_bbox[0]
            ln_x = col_x + (LANE_WIDTH - ln_w) // 2
            ln_y = lbl_y + (lbl_bbox[3] - lbl_bbox[1]) + 2
            draw.text((ln_x, ln_y), ln_label, fill=TEXT_DIM, font=font_small)

            # Draw bands
            for band in lane.bands:
                if has_mw and band.estimated_mw_kda and band.estimated_mw_kda > 0:
                    y_center = mw_to_y(band.estimated_mw_kda)
                elif band.position_y is not None:
                    y_center = position_to_y(band.position_y, lane.height)
                else:
                    continue

                base_color = _band_rgb(band)
                opacity = 0.7
                if band.relative_percent_lane is not None:
                    opacity = max(0.4, min(1.0, band.relative_percent_lane / 40.0))
                blended = tuple(int(base_color[c] * opacity + LANE_BG[c] * (1 - opacity)) for c in range(3))

                bx1 = col_x + BAND_INSET
                bx2 = col_x + LANE_WIDTH - BAND_INSET
                by1 = y_center - BAND_HEIGHT // 2
                by2 = y_center + BAND_HEIGHT // 2
                draw.rectangle([bx1, by1, bx2, by2], fill=blended)

                highlight = tuple(min(255, c + 40) for c in blended)
                draw.rectangle([bx1, y_center - 1, bx2, y_center + 1], fill=highlight)

            # Footer: lane type
            footer_text = lane.lane_type[:14] if lane.lane_type else ""
            if footer_text:
                ft_bbox = draw.textbbox((0, 0), footer_text, font=font_small)
                ft_w = ft_bbox[2] - ft_bbox[0]
                ft_x = col_x + (LANE_WIDTH - ft_w) // 2
                ft_y = HEADER_HEIGHT + BODY_HEIGHT + 4
                draw.text((ft_x, ft_y), footer_text, fill=TEXT_DIM, font=font_small)

        # MW scale on the right
        scale_x = LANE_GAP + n_lanes * (LANE_WIDTH + LANE_GAP) + 4

        visible_mws = [mw for mw in STANDARD_MWS if mw_min <= mw <= mw_max]
        if not visible_mws and has_mw:
            visible_mws = [round(mw_min_raw), round(mw_max_raw)]

        for mw in visible_mws:
            y = mw_to_y(mw)
            draw.line([(LANE_GAP, y), (scale_x - 2, y)], fill=SCALE_LINE, width=1)
            mw_label = f"{mw} kDa"
            draw.text((scale_x + 2, y - 6), mw_label, fill=TEXT_DIM, font=font_small)

        draw.text((scale_x + 2, HEADER_HEIGHT - 14), "MW", fill=TEXT_COLOR, font=font_bold)

        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def _render_electropherogram(self, lane, index: int = 0) -> BytesIO | None:
        """
        Render a single-lane electropherogram with matplotlib.

        Args:
            lane: LaneReportData with profile_data
            index: Lane index (for accent color selection)

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
        intensities = np.array(profile["intensities"], dtype=float)

        from .constants import (
            CHART_BAND_PALETTE_HEX,
            CHART_DARK_BG,
            CHART_DARK_GRID,
            CHART_DARK_TEXT,
            CHART_PROFILE_COLOR,
        )

        def _peak_color(b):
            return CHART_BAND_PALETTE_HEX.get((b.band_type_code or "OTHER").upper(), CHART_BAND_PALETTE_HEX["OTHER"])

        # Determine X-axis
        mw_values = profile.get("mw_values")
        has_mw = mw_values and any(v is not None and v > 0 for v in mw_values)

        if has_mw:
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
            x_values = np.array(profile["y_positions"], dtype=float)
            y_values = intensities
            x_label = "Y Position (pixels)"
            use_log_x = False

        if len(x_values) < 2:
            return None

        # Single profile colour matching the live chromatogram panel —
        # lane index is no longer used to pick a hue.
        del index  # kept in signature for caller compatibility
        hex_color = CHART_PROFILE_COLOR

        plt.rcParams["font.family"] = ["Inter", "Segoe UI", "DejaVu Sans", "sans-serif"]
        fig, ax = plt.subplots(figsize=(7, 2.5), dpi=150)
        fig.patch.set_facecolor(CHART_DARK_BG)
        ax.set_facecolor(CHART_DARK_BG)

        ax.plot(x_values, y_values, color=hex_color, linewidth=1.5, zorder=3)
        ax.fill_between(x_values, 0, y_values, color=hex_color, alpha=0.25, zorder=2)

        if use_log_x:
            ax.set_xscale("log")
            ax.invert_xaxis()
            from matplotlib.ticker import ScalarFormatter

            ax.xaxis.set_major_formatter(ScalarFormatter())
            ax.xaxis.get_major_formatter().set_scientific(False)

        # Peak markers
        for band in lane.bands:
            if has_mw and band.estimated_mw_kda and band.estimated_mw_kda > 0:
                bx = band.estimated_mw_kda
            elif band.position_y is not None and not has_mw:
                bx = float(band.position_y)
            else:
                continue

            idx = np.argmin(np.abs(x_values - bx))
            by = y_values[idx]

            peak_color = _peak_color(band)
            ax.plot(
                bx,
                by,
                "o",
                color=peak_color,
                markersize=6,
                markeredgecolor="white",
                markeredgewidth=1.5,
                zorder=5,
            )

            if band.estimated_mw_kda:
                ax.annotate(
                    f"{band.estimated_mw_kda:.0f} kDa",
                    (bx, by),
                    textcoords="offset points",
                    xytext=(0, 10),
                    fontsize=7,
                    color="white",
                    fontweight="bold",
                    ha="center",
                    zorder=6,
                )

        # Axis styling
        ax.set_xlabel(x_label, color=CHART_DARK_TEXT, fontsize=9)
        ax.set_ylabel("Intensity", color=CHART_DARK_TEXT, fontsize=9)
        ax.tick_params(colors=CHART_DARK_TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(CHART_DARK_GRID)
        ax.set_ylim(bottom=0)

        ax.set_title(
            f"{lane.sample_name} (L{lane.lane_number})",
            color="white",
            fontsize=10,
            fontweight="bold",
            pad=8,
        )

        plt.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    # ══════════════════════════════════════════════════════════════════
    # Word document section methods
    # ══════════════════════════════════════════════════════════════════

    def _add_cover_page(self):
        """Add the cover page (Phoresis logo if configured, then title)."""
        if PHORESIS_LOGO_PATH:
            try:
                logo_path = Path(__file__).resolve().parents[3] / PHORESIS_LOGO_PATH
                if logo_path.exists():
                    paragraph = self.document.add_paragraph()
                    from docx.enum.text import WD_ALIGN_PARAGRAPH

                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    run = paragraph.add_run()
                    run.add_picture(str(logo_path), width=Inches(1.5))
            except Exception as e:
                logger.warning(f"Failed to add logo: {e}")

        for _ in range(2):
            self.document.add_paragraph()

        self._add_paragraph(
            "DENSITOMETRY ANALYSIS REPORT",
            font_size=TITLE_SIZE,
            bold=True,
            color=PHORESIS_ACCENT,
            align="center",
            font_name=HEADING_FONT,
        )

        self.document.add_paragraph()

        self._add_paragraph(
            self.data.analysis_name,
            font_size=20,
            bold=True,
            align="center",
            font_name=HEADING_FONT,
        )

        self._add_paragraph(
            self.data.gel_type,
            font_size=14,
            align="center",
        )

        for _ in range(2):
            self.document.add_paragraph()

        avg_purity_str = f"{self.data.average_purity:.1f}%" if self.data.average_purity is not None else "N/A"
        self._add_paragraph(
            f"Lanes: {self.data.total_lanes_count} | "
            f"Bands: {self.data.total_bands_count} | "
            f"Avg Purity: {avg_purity_str} | "
            f"Status: {self.data.analysis_status}",
            font_size=12,
            align="center",
            color=MUTED_GRAY,
        )

        for _ in range(5):
            self.document.add_paragraph()

        self._add_paragraph(
            f"Generated: {self.data.report_generated_at}",
            font_size=SMALL_SIZE,
            align="center",
            color=MUTED_GRAY,
        )
        self._add_paragraph(
            f"Generated by: {self.data.report_generated_by}",
            font_size=SMALL_SIZE,
            align="center",
            color=MUTED_GRAY,
        )

        self.document.add_page_break()

    def _add_overview(self, section_number: int):
        """Add analysis overview section."""
        try:
            self._add_section_heading(f"{section_number}. ANALYSIS OVERVIEW")

            avg_purity_str = f"{self.data.average_purity:.1f}%" if self.data.average_purity is not None else "N/A"
            calibration_status = "Yes" if self.data.has_calibration else "No"
            if self.data.has_calibration and self.data.calibrations:
                cal = self.data.calibrations[0]
                calibration_status = f"Yes — {cal.template_name} (R²={cal.r_squared:.3f})"

            data = [
                ("Analysis Name", self.data.analysis_name),
                ("Status", self.data.analysis_status),
                ("Gel Type", self.data.gel_type),
                ("Image", self.data.image_title),
                ("Analyst", self.data.created_by_name),
                ("Date", self.data.created_at),
                ("Total Lanes", str(self.data.total_lanes_count)),
                ("Total Bands", str(self.data.total_bands_count)),
                ("Average Purity", avg_purity_str),
                ("MW Calibration", calibration_status),
            ]

            if self.data.densitometry_computed_at:
                data.append(("Densitometry Computed", self.data.densitometry_computed_at))

            if self.data.notes:
                notes_text = self.data.notes[:500] + "..." if len(self.data.notes) > 500 else self.data.notes
                data.append(("Notes", notes_text))

            self._add_info_table(data, widths=[2.5, 4.5])

        except Exception as e:
            logger.error(f"Error in _add_overview: {e}")

    def _add_sample_summary(self, section_number: int):
        """Add sample summary table with all lanes."""
        try:
            self._add_section_heading(f"{section_number}. SAMPLE SUMMARY")

            if not self.data.lanes:
                self._add_paragraph("No lanes detected.", font_size=SMALL_SIZE)
                return

            headers = [
                "#",
                "Sample",
                "Type",
                "Condition",
                "Load (µg)",
                "Bands",
                "Purity (%)",
                "Fit Quality",
                "Notes",
            ]

            rows = []
            for lane in self.data.lanes:
                purity_str = f"{lane.poi_percentage:.1f}" if lane.poi_percentage is not None else "-"
                load_str = "-"
                if lane.protein_load_ug is not None:
                    load_str = f"{lane.protein_load_ug:.1f}"
                    if lane.protein_load_type:
                        load_str += f" ({lane.protein_load_type})"
                condition_str = lane.condition or "-"
                notes_str = (lane.notes[:30] + "...") if lane.notes and len(lane.notes) > 30 else (lane.notes or "-")

                # Average fit quality from bands
                qualities = [b.fit_quality for b in lane.bands if b.fit_quality]
                fit_quality = max(set(qualities), key=qualities.count) if qualities else "-"

                rows.append(
                    [
                        str(lane.lane_number),
                        lane.sample_name,
                        lane.lane_type,
                        condition_str,
                        load_str,
                        str(len(lane.bands)),
                        purity_str,
                        fit_quality,
                        notes_str,
                    ]
                )

            self._add_data_table(headers, rows)

        except Exception as e:
            logger.error(f"Error in _add_sample_summary: {e}")

    def _add_gel_image(self, section_number: int):
        """Add full gel image with optional band overlays."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        try:
            self._add_section_heading(f"{section_number}. FULL GEL IMAGE")

            gel_buf = self._render_full_gel_image(show_bands=self.band_overlay)
            if gel_buf:
                paragraph = self.document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run()
                run.add_picture(gel_buf, width=Inches(IMAGE_FULL_WIDTH))
                self.document.add_paragraph()
            else:
                self._add_paragraph(
                    "[Gel image not available]",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                    align="center",
                )

        except Exception as e:
            logger.error(f"Error in _add_gel_image: {e}")

    def _add_digital_gel(self, section_number: int):
        """Add digital gel visualization for all lanes."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        try:
            self._add_section_heading(f"{section_number}. DIGITAL GEL (ALL LANES)")

            self._add_paragraph(
                "Digital lane reconstructions showing band patterns and intensities for all lanes in the analysis.",
                font_size=SMALL_SIZE,
            )

            digital_buf = self._render_digital_gel(self.data.lanes)
            if digital_buf:
                paragraph = self.document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run()
                run.add_picture(digital_buf, width=Inches(IMAGE_FULL_WIDTH))
                self.document.add_paragraph()
            else:
                self._add_paragraph(
                    "[Digital gel rendering failed]",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                    align="center",
                )

        except Exception as e:
            logger.error(f"Error in _add_digital_gel: {e}")

    def _add_poi_purity(self, section_number: int):
        """Add POI purity chart."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        try:
            self._add_section_heading(f"{section_number}. POI PURITY")

            # Check if any lane has purity data
            has_purity = any(lane.poi_percentage is not None for lane in self.data.lanes)
            if not has_purity:
                self._add_paragraph(
                    "No purity data available.",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                )
                return

            from .poi_purity_chart import render_poi_purity_chart

            purity_data = [
                {
                    "label": lane.sample_name or f"Lane {lane.lane_number}",
                    "purity": lane.poi_percentage,
                }
                for lane in self.data.lanes
            ]

            chart_buf = render_poi_purity_chart(purity_data, dark_theme=True, dpi=150)
            if chart_buf:
                paragraph = self.document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run()
                run.add_picture(chart_buf, width=Inches(IMAGE_FULL_WIDTH))
                self.document.add_paragraph()
            else:
                self._add_paragraph(
                    "[POI purity chart rendering failed]",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                    align="center",
                )

        except Exception as e:
            logger.error(f"Error in _add_poi_purity: {e}")

    def _add_lane_details(self, section_number: int):
        """Add per-lane detail sections with electropherogram and band table."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        try:
            first_lane = True
            for i, lane in enumerate(self.data.lanes):
                if first_lane:
                    self._add_section_heading(f"{section_number}. LANE DETAILS")
                    first_lane = False
                else:
                    self.document.add_page_break()

                self._add_section_heading(
                    f"Lane {lane.lane_number}: {lane.sample_name}",
                    level=2,
                )

                # Lane info table
                purity_str = f"{lane.poi_percentage:.1f}%" if lane.poi_percentage is not None else "N/A"
                total_area_str = (
                    f"{lane.total_integrated_area:.0f}" if lane.total_integrated_area is not None else "N/A"
                )
                load_str = "N/A"
                if lane.protein_load_ug is not None:
                    load_str = f"{lane.protein_load_ug:.1f} µg"
                    if lane.protein_load_type:
                        load_str += f" ({lane.protein_load_type})"

                data = [
                    ("Lane Type", lane.lane_type),
                    ("Sample", lane.sample_name),
                    ("Condition", lane.condition or "N/A"),
                    ("Protein Load", load_str),
                    ("Purity", purity_str),
                    ("Total Integrated Area", total_area_str),
                    ("Bands", str(len(lane.bands))),
                ]

                if lane.notes:
                    data.append(("Notes", lane.notes))

                self._add_info_table(data, widths=[2.0, 5.0])

                # Electropherogram
                if lane.profile_data:
                    try:
                        chart_buf = self._render_electropherogram(lane, index=i)
                        if chart_buf:
                            self._add_paragraph("Electropherogram:", font_size=SMALL_SIZE, bold=True)
                            paragraph = self.document.add_paragraph()
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = paragraph.add_run()
                            run.add_picture(chart_buf, width=Inches(IMAGE_FULL_WIDTH))
                    except Exception as e:
                        logger.warning(f"Failed to render electropherogram for lane {lane.lane_number}: {e}")
                        self._add_paragraph(
                            f"[Failed to render profile for {lane.sample_name}]",
                            font_size=SMALL_SIZE,
                            color=MUTED_GRAY,
                            align="center",
                        )

                # 3D Terrain view (inline after electropherogram)
                if (
                    self._should_include("terrain_view")
                    and lane.profile_data
                    and lane.lane_type not in ("MW Ladder", "Empty")
                ):
                    try:
                        from .terrain_chart import render_terrain_chart

                        terrain_buf = render_terrain_chart(
                            lane,
                            figsize=(7, 4),
                            dpi=150,
                            dark_theme=True,
                        )
                        if terrain_buf:
                            self._add_paragraph("3D Terrain View:", font_size=SMALL_SIZE, bold=True)
                            paragraph = self.document.add_paragraph()
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = paragraph.add_run()
                            run.add_picture(terrain_buf, width=Inches(IMAGE_FULL_WIDTH))
                    except Exception as e:
                        logger.warning(f"Failed to render terrain for lane {lane.lane_number}: {e}")

                # Band data table
                if lane.bands:
                    self._add_paragraph("Band Densitometry:", font_size=SMALL_SIZE, bold=True)

                    headers = [
                        "#",
                        "Type",
                        "MW (kDa)",
                        "Area",
                        "% Lane",
                        "% Gel",
                        "FWHM",
                        "R²",
                        "Quality",
                    ]

                    rows = []
                    for band in lane.bands:
                        band_num = str(band.band_number) if band.band_number else "-"
                        mw_str = f"{band.estimated_mw_kda:.1f}" if band.estimated_mw_kda is not None else "-"
                        area_str = f"{band.corrected_area:.0f}" if band.corrected_area is not None else "-"
                        pct_lane_str = (
                            f"{band.relative_percent_lane:.1f}" if band.relative_percent_lane is not None else "-"
                        )
                        pct_gel_str = (
                            f"{band.relative_percent_gel:.1f}" if band.relative_percent_gel is not None else "-"
                        )
                        fwhm_str = f"{band.fwhm:.2f}" if band.fwhm is not None else "-"
                        r2_str = f"{band.fit_r_squared:.3f}" if band.fit_r_squared is not None else "-"
                        quality_str = band.fit_quality or "-"

                        rows.append(
                            [
                                band_num,
                                band.band_type,
                                mw_str,
                                area_str,
                                pct_lane_str,
                                pct_gel_str,
                                fwhm_str,
                                r2_str,
                                quality_str,
                            ]
                        )

                    self._add_data_table(headers, rows)

                self.document.add_paragraph()

        except Exception as e:
            logger.error(f"Error in _add_lane_details: {e}")

    def _add_terrain_view(self, section_number: int):
        """Add 3D terrain view for each sample lane."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        from .terrain_chart import render_terrain_chart

        try:
            sample_lanes = [lane for lane in self.data.lanes if lane.lane_type not in ("MW Ladder", "Empty")]

            if not sample_lanes:
                return

            first_lane = True
            for lane in sample_lanes:
                if not lane.profile_data:
                    continue

                if first_lane:
                    self._add_section_heading(f"{section_number}. 3D TERRAIN VIEW")
                    first_lane = False
                else:
                    self.document.add_page_break()

                self._add_section_heading(
                    f"Terrain — {lane.sample_name} (L{lane.lane_number})",
                    level=2,
                )

                try:
                    chart_buf = render_terrain_chart(
                        lane,
                        figsize=(7, 4),
                        dpi=150,
                        dark_theme=True,
                    )
                    if chart_buf:
                        paragraph = self.document.add_paragraph()
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        run = paragraph.add_run()
                        run.add_picture(chart_buf, width=Inches(IMAGE_FULL_WIDTH))
                        self.document.add_paragraph()
                    else:
                        self._add_paragraph(
                            "[Terrain chart not available — insufficient profile data]",
                            font_size=SMALL_SIZE,
                            color=MUTED_GRAY,
                            align="center",
                        )
                except Exception as e:
                    logger.warning(f"Failed to render terrain for lane {lane.lane_number}: {e}")
                    self._add_paragraph(
                        f"[Failed to render terrain for {lane.sample_name}]",
                        font_size=SMALL_SIZE,
                        color=MUTED_GRAY,
                        align="center",
                    )

        except Exception as e:
            logger.error(f"Error in _add_terrain_view: {e}")

    def _add_materials_methods(self, section_number: int):
        """Add materials and methods section."""
        try:
            self._add_section_heading(f"{section_number}. MATERIALS & METHODS")

            # Densitometry
            self._add_section_heading("Densitometry Analysis", level=2)
            self._add_paragraph(METHODOLOGY_DENSITOMETRY.strip(), font_size=SMALL_SIZE)
            self.document.add_paragraph()

            # MW Calibration
            if self.data.has_calibration:
                self._add_section_heading("Molecular Weight Calibration", level=2)
                self._add_paragraph(METHODOLOGY_CALIBRATION.strip(), font_size=SMALL_SIZE)
                self.document.add_paragraph()

            # Purity
            if any(lane.poi_percentage is not None for lane in self.data.lanes):
                self._add_section_heading("Purity Calculation", level=2)
                self._add_paragraph(METHODOLOGY_PURITY.strip(), font_size=SMALL_SIZE)
                self.document.add_paragraph()

        except Exception as e:
            logger.error(f"Error in _add_materials_methods: {e}")

    def _add_metadata_footer(self):
        """Add metadata footer."""
        try:
            self.document.add_paragraph()
            self._add_paragraph("---", font_size=8, align="center", color=MUTED_GRAY)
            self._add_paragraph(
                f"Report generated: {self.data.report_generated_at}",
                font_size=8,
                align="center",
                color=MUTED_GRAY,
            )
            self._add_paragraph(
                f"Generated by: {self.data.report_generated_by}",
                font_size=8,
                align="center",
                color=MUTED_GRAY,
            )
            self._add_paragraph(
                f"Software: {self.data.software_version}",
                font_size=8,
                align="center",
                color=MUTED_GRAY,
            )
        except Exception as e:
            logger.error(f"Error in _add_metadata_footer: {e}")

    # ══════════════════════════════════════════════════════════════════
    # Build
    # ══════════════════════════════════════════════════════════════════

    def build(self) -> BytesIO:
        """Build the complete Word document and return as BytesIO."""
        logger.info(f"Building Densitometry Word report for '{self.data.analysis_name}'")

        try:
            self._add_cover_page()
        except Exception as e:
            logger.error(f"Failed to add cover page: {e}")

        # Section numbering (only count included sections)
        section_num = 0

        section_map = [
            ("overview", self._add_overview, "overview"),
            ("sample_summary", self._add_sample_summary, "sample summary"),
            ("gel_image", self._add_gel_image, "gel image"),
            ("digital_gel", self._add_digital_gel, "digital gel"),
            ("poi_purity", self._add_poi_purity, "POI purity"),
            ("lane_details", self._add_lane_details, "lane details"),
            ("materials_methods", self._add_materials_methods, "materials & methods"),
        ]

        for key, method, desc in section_map:
            if self._should_include(key):
                section_num += 1
                try:
                    self.document.add_page_break()
                    method(section_num)
                except Exception as e:
                    logger.error(f"Failed to add section '{desc}': {e}")

        try:
            self._add_metadata_footer()
        except Exception as e:
            logger.error(f"Failed to add metadata footer: {e}")

        logger.info(f"Densitometry Word report built for '{self.data.analysis_name}'")
        return self._save()
