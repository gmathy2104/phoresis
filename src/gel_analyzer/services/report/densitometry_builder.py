"""
Word document builder for densitometry analysis reports.

Generates comprehensive analysis reports with the Phoresis brand
palette (accent-600 blue, Inter), server-side rendered gel images,
digital gel visualization, electropherograms, 3D terrain views, and
detailed lane analysis.
"""

import contextlib
from io import BytesIO
from pathlib import Path

from docx.shared import Inches

from phoresis_core.logging_config import get_logger

from .builder import BaseReportBuilder
from .constants import (
    BAND_PALETTE_HEX,
    HEADING_FONT,
    IMAGE_FULL_WIDTH,
    LANE_PALETTE_HEX,
    METHODOLOGY_CALIBRATION,
    METHODOLOGY_DENSITOMETRY,
    METHODOLOGY_QUANTIFICATION,
    MUTED_GRAY,
    PHORESIS_ACCENT,
    PHORESIS_LOGO_PATH,
    READOUT_METHODOLOGY,
    SMALL_SIZE,
    TITLE_SIZE,
    calibration_range_display,
    is_outside_calibration_range,
    saturation_text,
)
from .densitometry_data_collector import DensitometryReportData
from .digital_gel import render_digital_gel
from .page_rows import card_text, cell_text, readout_card, sample_text

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
        Render the annotated gel via the shared ``gel_overlay`` renderer.

        Args:
            show_bands: True → variant=FULL (all band overlays);
                False → variant=LANES_ONLY (outlines + labels only).

        Returns:
            BytesIO with PNG image, or None if the image isn't available.
        """
        if not self.data.gel_image_id:
            return None

        try:
            from gel_analyzer.models import GelImage

            from .gel_overlay import GelOverlayVariant, render_gel_overlay

            gel_image = GelImage.objects.get(pk=self.data.gel_image_id)
            image_file = gel_image.display_file or gel_image.original_file
            if not image_file:
                return None
            variant = GelOverlayVariant.FULL if show_bands else GelOverlayVariant.LANES_ONLY
            calibration = self.data.calibrations[0] if getattr(self.data, "calibrations", None) else None
            return render_gel_overlay(
                image_file,
                self.data.lanes,
                variant=variant,
                calibration=calibration,
            )
        except Exception as e:
            logger.warning(f"Failed to render full gel image: {e}", exc_info=True)
            return None

    def _render_digital_gel(self, lanes) -> BytesIO | None:
        """Delegate to the shared renderer (footer = lane type)."""
        return render_digital_gel(lanes, calibration=None, footer_field="lane_type")

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

        from .constants import CHART_DARK_GRID, CHART_DARK_TEXT, CHART_PROFILE_COLOR

        PEAK_COLORS = {
            "Protein of Interest": BAND_PALETTE_HEX["POI"],  # #A855F7 purple
            "Other": BAND_PALETTE_HEX["OTHER"],  # #22C55E green
            "MW Ladder": BAND_PALETTE_HEX["MW_REFERENCE"],  # #F97316 orange
            "MW Reference": BAND_PALETTE_HEX["MW_REFERENCE"],  # #F97316 orange
            "Calibration Point": BAND_PALETTE_HEX["CALIBRATION"],  # #F87171 red-400
        }

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

        fig, ax = plt.subplots(figsize=(7, 2.5), dpi=200)
        fig.patch.set_facecolor("#1e1e22")
        ax.set_facecolor("#1e1e22")

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

            peak_color = PEAK_COLORS.get(band.band_type, "#9E9E9E")
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

        fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.18)
        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
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
            f"{self.data.assay_label} · {self.data.analysis_status}",
            font_size=14,
            align="center",
        )

        for _ in range(2):
            self.document.add_paragraph()

        avg_purity_str = self.data.average_purity_text
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

            calibration_status = "Yes" if self.data.has_calibration else "No"
            if self.data.has_calibration and self.data.calibrations:
                cal = self.data.calibrations[0]
                calibration_status = f"Yes — {cal.template_name} (R²={cal.r_squared:.3f})"

            # The page's readout card (Mean purity, Main band (mean), HCP reference) stands for the readout.
            card = readout_card(self.data.cards)
            data = [
                ("Analysis Name", self.data.analysis_name),
                (
                    "Status",
                    self.data.analysis_status + (f" — {self.data.status_hint}" if self.data.status_hint else ""),
                ),
                ("Assay", self.data.assay_label),
                ("Gel Type", self.data.gel_type),
                ("Image", self.data.image_title),
                ("Analyst", self.data.created_by_name),
                ("Date", self.data.created_at),
                ("Total Lanes", str(self.data.total_lanes_count)),
                ("Total Bands", str(self.data.total_bands_count)),
            ]
            if card is not None:
                data.append((card["label"], card_text(card)))
            data.append(("MW Calibration", calibration_status))

            if self.data.densitometry_computed_at:
                data.append(("Densitometry Computed", self.data.densitometry_computed_at))

            if self.data.notes:
                notes_text = self.data.notes[:500] + "..." if len(self.data.notes) > 500 else self.data.notes
                data.append(("Notes", notes_text))

            self._add_info_table(data, widths=[2.5, 4.5])

            # The page's "To check" items, warnings first.
            self._add_section_heading("To check", level=2)
            if not self.data.checks:
                self._add_paragraph("Nothing to check.", font_size=SMALL_SIZE)
            for check in self.data.checks:
                mark = "⚠" if check["level"] == "warn" else "ℹ"
                self._add_paragraph(f"{mark} {check['title']}", font_size=SMALL_SIZE, bold=True)
                if check.get("detail"):
                    self._add_paragraph(check["detail"], font_size=SMALL_SIZE, color=MUTED_GRAY)

        except Exception as e:
            logger.error(f"Error in _add_overview: {e}")

    def _add_sample_summary(self, section_number: int):
        """Add sample summary table with all lanes."""
        try:
            self._add_section_heading(f"{section_number}. SAMPLE SUMMARY")

            if not self.data.lanes:
                self._add_paragraph("No lanes detected.", font_size=SMALL_SIZE)
                return

            # The lane's own fields, the readout's columns with the analysis page's cells (page_rows), the fit.
            columns = self.data.readout_columns
            headers = (
                ["#", "Sample", "Type", "Condition", "Load (µg)"]
                + [column["label"] for column in columns]
                + ["Fit Quality", "Notes"]
            )
            # The page's saturation check, lane by lane: a column only on a gel that has a saturated band.
            flagged = any(lane.saturated_bands for lane in self.data.lanes)
            if flagged:
                headers.append("Saturated")

            rows = []
            for lane in self.data.lanes:
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
                        sample_text(lane) + (" (REF)" if lane.is_reference else ""),
                        lane.lane_type,
                        condition_str,
                        load_str,
                    ]
                    + [cell_text(lane, column["key"]) or "-" for column in columns]
                    + [fit_quality, notes_str]
                    + (["⚠ " + ", ".join(lane.saturated_bands) if lane.saturated_bands else ""] if flagged else [])
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
        """The chart of the gel's readout (readout_chart): purity, HMWS / main band / LMWS or HCP % of reference."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        from .readout_chart import chart_title, render_readout_chart

        try:
            title = chart_title(self.data.readout, self.data.lanes)
            self._add_section_heading(f"{section_number}. {(title or 'Readout').upper()}")
            if title is None:
                self._add_paragraph(
                    "This gel has no readout: its bands are annotated, nothing is computed on it.",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                )
                return

            mean = None
            if self.data.average_purity is not None:
                mean = (self.data.average_purity, f"Mean {self.data.average_purity_text}")
            chart_buf = render_readout_chart(
                self.data.readout, self.data.lanes, mean=mean, figsize=(7, 3.5), dpi=150, dark_theme=True
            )
            if chart_buf:
                paragraph = self.document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run()
                run.add_picture(chart_buf, width=Inches(IMAGE_FULL_WIDTH))
                self.document.add_paragraph()
            else:
                self._add_paragraph(
                    "[No lane value to chart yet]",
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

                title = f"Lane {lane.lane_number}: {sample_text(lane)}"
                self._add_section_heading(f"{title} (reference)" if lane.is_reference else title, level=2)

                # Lane info table: the lane's fields, its cells of the readout's columns (page_rows), its total area
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
                    ("Sample", sample_text(lane)),
                    ("Condition", lane.condition or "N/A"),
                    ("Protein Load", load_str),
                ]
                data += [
                    (column["label"], cell_text(lane, column["key"]) or "N/A")
                    for column in self.data.readout_columns
                    if column["key"] in lane.readout_cells
                ]
                data.append(("Total Integrated Area", total_area_str))

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
                        "Band",
                        "Type",
                        "MW (kDa)",
                        "Area",
                        "% Lane",
                        "% Gel",
                        "FWHM",
                        "R²",
                        "Quality",
                        "Saturation",
                    ]

                    rows = []
                    for band in lane.bands:
                        band_num = band.name or "-"
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
                                saturation_text(band),
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

    def _render_calibration_curve_png(self) -> BytesIO | None:
        """High-DPI matplotlib PNG of the calibration curve: calibration points,
        excluded points faded, fit line (sampled polyline), control points (red
        if out-of-spec). Returns None if no points."""
        data = self.data
        if not data.has_quantification or not data.quant_points:
            return None
        try:
            import matplotlib
            import numpy as np

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            from .constants import mpl_style  # Ph0 helper (rcParams, dpi>=200)

            with contextlib.suppress(Exception):
                mpl_style()

            fig, ax = plt.subplots(figsize=(6.5, 4.0), dpi=200)

            # Calibration points (x = corrected_area, y = load_amount)
            inc_x = [
                p.corrected_area
                for p in data.quant_points
                if not p.is_excluded and p.corrected_area is not None and p.load_amount is not None
            ]
            inc_y = [
                p.load_amount
                for p in data.quant_points
                if not p.is_excluded and p.corrected_area is not None and p.load_amount is not None
            ]
            exc_x = [
                p.corrected_area
                for p in data.quant_points
                if p.is_excluded and p.corrected_area is not None and p.load_amount is not None
            ]
            exc_y = [
                p.load_amount
                for p in data.quant_points
                if p.is_excluded and p.corrected_area is not None and p.load_amount is not None
            ]

            calib_color = LANE_PALETTE_HEX.get("CALIBRATION", "#F87171")
            if inc_x:
                ax.scatter(inc_x, inc_y, c=calib_color, s=42, label="Calibration", zorder=3)
            if exc_x:
                ax.scatter(
                    exc_x,
                    exc_y,
                    facecolors="none",
                    edgecolors=calib_color,
                    s=42,
                    alpha=0.4,
                    label="Excluded",
                    zorder=2,
                )

            # Fit line — sampled across the calibration x-range using the service
            if inc_x and len(inc_x) >= 2:
                from gel_analyzer.models import ProteinQuantCalibration
                from gel_analyzer.services.quantification.models import QuantParams, QuantResult
                from gel_analyzer.services.quantification.service import ProteinQuantCalibrationService

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
                    xs = np.linspace(min(inc_x), max(inc_x), 50)
                    ys = [svc.project(float(x), fit_result) for x in xs]
                    if all(y is not None for y in ys):
                        ax.plot(xs, ys, color="#334155", lw=1.5, label="Fit", zorder=1)

            # Control points (red if out-of-spec, else green)
            for c in data.quant_controls:
                if c.predicted_amount is None or c.known_amount is None:
                    continue
                color = "#EF4444" if c.out_of_spec else LANE_PALETTE_HEX.get("CONTROL", "#22C55E")
                ax.scatter([c.known_amount], [c.predicted_amount], marker="s", c=color, s=40, zorder=4)

            ax.set_xlabel("Corrected area")
            ax.set_ylabel(f"Amount ({data.quant_calibration.unit})" if data.quant_calibration else "Amount")
            ax.set_title("Calibration curve")
            ax.legend(loc="best", fontsize=8)

            buf = BytesIO()
            fig.savefig(buf, format="png", facecolor="white")
            plt.close(fig)
            buf.seek(0)
            return buf
        except Exception as e:
            logger.warning(f"Failed to render calibration curve: {e}")
            return None

    def _add_quantification(self, section_num: int):
        """Word: Protein Quantification section (methodology + curve + Tables A/B/C)."""
        try:
            data = self.data
            self._add_section_heading(f"{section_num}. Protein Quantification", level=1)

            if not data.has_quantification or data.quant_calibration is None:
                self._add_paragraph(
                    "No active protein quantification calibration for this analysis.",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                )
                return

            cal = data.quant_calibration
            # Methodology block
            self._add_paragraph(METHODOLOGY_QUANTIFICATION.strip(), font_size=SMALL_SIZE)
            meta_lines = [
                f"Method: {cal.method}",
                f"Unit: {cal.unit}",
                f"Equation: {cal.equation}",
                f"R²: {cal.r_squared:.4f} ({cal.r_squared_quality})",
                f"Points used / excluded: {cal.n_points} / {cal.n_excluded}",
                f"Fitted by: {cal.created_by_name} on {cal.created_at}",
                "Recovery in-spec range: 80–120%",
            ]
            if cal.last_recomputed_at:
                meta_lines.append(f"Note: fit auto-recomputed (drift) at {cal.last_recomputed_at}")
            for line in meta_lines:
                self._add_paragraph(line, font_size=SMALL_SIZE)
            self.document.add_paragraph()

            # Calibration curve PNG
            curve = self._render_calibration_curve_png()
            if curve is not None:
                self.document.add_picture(curve, width=Inches(IMAGE_FULL_WIDTH))
                self.document.add_paragraph()

            if not data.quant_points:
                self._add_paragraph(
                    "Fit unavailable — calibration data incomplete.",
                    font_size=SMALL_SIZE,
                    color=MUTED_GRAY,
                )
                return

            # Table A — calibration points
            self._add_section_heading("Calibration Points", level=2)
            headers_a = ["Lane #", "Load", "Unit", "Corrected area", "Residual %", "Excluded"]
            rows_a = [
                [
                    str(p.lane_number),
                    f"{p.load_amount:.3g}" if p.load_amount is not None else "—",
                    p.load_unit or "",
                    f"{p.corrected_area:.1f}" if p.corrected_area is not None else "—",
                    f"{p.residual_pct:.2f}" if p.residual_pct is not None else "—",
                    "Yes" if p.is_excluded else "",
                ]
                for p in data.quant_points
            ]
            self._add_data_table(headers_a, rows_a)
            self.document.add_paragraph()

            # Table B — controls / QC (omit if no controls)
            if data.quant_controls:
                self._add_section_heading("Controls / QC Recovery", level=2)
                headers_b = ["Lane #", "Known", "Predicted", "Recovery %", "Range", "Flag"]
                rows_b = [
                    [
                        str(c.lane_number),
                        f"{c.known_amount:.3g}" if c.known_amount is not None else "—",
                        f"{c.predicted_amount:.3g}" if c.predicted_amount is not None else "—",
                        f"{c.recovery_pct:.2f}" if c.recovery_pct is not None else "—",
                        calibration_range_display(c.calibration_range),
                        "OUT OF SPEC" if c.out_of_spec else "OK",
                    ]
                    for c in data.quant_controls
                ]
                self._add_data_table(
                    headers_b,
                    rows_b,
                    highlight_rows=[i for i, c in enumerate(data.quant_controls) if c.out_of_spec],
                )
                self.document.add_paragraph()

            # Table C — sample estimated amounts
            if data.quant_samples:
                self._add_section_heading("Sample Estimated Amounts", level=2)
                headers_c = ["Lane #", "Sample", "Est. amount", "Unit", "Range"]
                rows_c = [
                    [
                        str(s.lane_number),
                        s.sample_name or "—",
                        f"{s.estimated_amount:.3g}" if s.estimated_amount is not None else "N/A",
                        s.unit or "",
                        calibration_range_display(s.calibration_range),
                    ]
                    for s in data.quant_samples
                ]
                self._add_data_table(
                    headers_c,
                    rows_c,
                    highlight_rows=[
                        i for i, s in enumerate(data.quant_samples) if is_outside_calibration_range(s.calibration_range)
                    ],
                )
        except Exception as e:
            logger.error(f"Error in _add_quantification: {e}")

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

            # What the lane values mean, for the readout the gel is read for
            if self.data.readout in READOUT_METHODOLOGY:
                title, text = READOUT_METHODOLOGY[self.data.readout]
                self._add_section_heading(title, level=2)
                self._add_paragraph(text.strip(), font_size=SMALL_SIZE)
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
            ("quantification", self._add_quantification, "quantification"),
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
