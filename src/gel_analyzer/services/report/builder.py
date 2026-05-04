"""
Word document builder for gel analysis reports.

Generates comprehensive Word documents with GSK branding, charts, and tables.
"""

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from phoresis_core.logging_config import get_logger

from .constants import (
    BODY_FONT,
    BODY_SIZE,
    GSK_LOGO_PATH,
    GSK_ORANGE,
    HEADING_FONT,
    IMAGE_DIGITAL_LANE_WIDTH,
    IMAGE_FULL_WIDTH,
    IMAGE_HALF_WIDTH,
    METHODOLOGY_CALIBRATION,
    METHODOLOGY_DENSITOMETRY,
    METHODOLOGY_PURITY,
    MUTED_GRAY,
    SECTION_H1_SIZE,
    SECTION_H2_SIZE,
    SECTION_H3_SIZE,
    SMALL_SIZE,
    TABLE_HEADER_BG,
    TABLE_SIZE,
    TITLE_SIZE,
)
from .data_collector import LaneReportData, ReportData

logger = get_logger(__name__)


class BaseReportBuilder:
    """
    Base class with shared methods for Word document report generation.
    Provides common utilities for styles, layout, paragraphs, tables, and images.
    """

    def __init__(self):
        """Initialize base report builder."""
        self.document = Document()
        self._setup_styles()
        self._setup_page_layout()

    def _setup_styles(self):
        """Configure GSKPrecision fonts and document styles."""
        style = self.document.styles["Normal"]
        font = style.font
        font.name = BODY_FONT
        font.size = Pt(BODY_SIZE)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    def _setup_page_layout(self):
        """Set page margins."""
        for section in self.document.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

    def _add_paragraph(
        self,
        text: str,
        font_size: int = BODY_SIZE,
        bold: bool = False,
        color: tuple | None = None,
        align: str = "left",
        font_name: str = BODY_FONT,
        space_after: int = 6,
    ):
        """Add a formatted paragraph."""
        p = self.document.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(font_size)
        run.font.name = font_name

        if color:
            run.font.color.rgb = RGBColor(*color)

        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        p.paragraph_format.space_after = Pt(space_after)
        return p

    def _add_section_heading(self, text: str, level: int = 1):
        """Add a section heading with GSK orange color."""
        if level == 1:
            font_size = SECTION_H1_SIZE
        elif level == 2:
            font_size = SECTION_H2_SIZE
        else:
            font_size = SECTION_H3_SIZE

        self._add_paragraph(
            text, font_size=font_size, bold=True, color=GSK_ORANGE, font_name=HEADING_FONT, space_after=12
        )

    def _add_info_table(self, data: list, widths: list | None = None):
        """Add a two-column info table (label-value pairs)."""
        if not data:
            return

        table = self.document.add_table(rows=len(data), cols=2)
        table.style = "Table Grid"

        if widths:
            for i, width in enumerate(widths):
                for cell in table.columns[i].cells:
                    cell.width = Inches(width)

        for i, (label, value) in enumerate(data):
            label_cell = table.rows[i].cells[0]
            label_para = label_cell.paragraphs[0]
            label_run = label_para.add_run(str(label))
            label_run.bold = True
            label_run.font.size = Pt(SMALL_SIZE)
            label_run.font.name = HEADING_FONT
            label_run.font.color.rgb = RGBColor(*MUTED_GRAY)

            value_cell = table.rows[i].cells[1]
            value_para = value_cell.paragraphs[0]
            value_run = value_para.add_run(str(value) if value is not None else "-")
            value_run.font.size = Pt(SMALL_SIZE)
            value_run.font.name = BODY_FONT

        self.document.add_paragraph()

    def _add_data_table(self, headers: list, rows: list):
        """Add a data table with styled headers."""
        if not rows:
            return

        table = self.document.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = "Table Grid"

        # Header row
        header_row = table.rows[0]
        for i, header in enumerate(headers):
            cell = header_row.cells[i]
            para = cell.paragraphs[0]
            run = para.add_run(header)
            run.bold = True
            run.font.size = Pt(TABLE_SIZE)
            run.font.name = HEADING_FONT
            run.font.color.rgb = RGBColor(255, 255, 255)

            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), TABLE_HEADER_BG)
            cell._tc.get_or_add_tcPr().append(shading)

        # Data rows
        for i, row_data in enumerate(rows):
            row = table.rows[i + 1]
            for j, value in enumerate(row_data):
                cell = row.cells[j]
                para = cell.paragraphs[0]
                run = para.add_run(str(value) if value is not None else "-")
                run.font.size = Pt(TABLE_SIZE)
                run.font.name = BODY_FONT

        self.document.add_paragraph()

    def _add_captured_image(self, image_key: str, width: float = IMAGE_FULL_WIDTH):
        """
        Add a captured image from the images dict.

        Args:
            image_key: Key in self.images dict
            width: Width in inches
        """
        if image_key not in self.images:
            logger.warning(f"Image {image_key} not found in images dict")
            self._add_paragraph(
                f"[Image '{image_key}' not available]", font_size=SMALL_SIZE, color=MUTED_GRAY, align="center"
            )
            return

        try:
            image_bytes = self.images[image_key]
            image_stream = BytesIO(image_bytes)

            paragraph = self.document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run()
            run.add_picture(image_stream, width=Inches(width))

            self.document.add_paragraph()  # Spacing

        except Exception as e:
            logger.error(f"Failed to add image {image_key}: {e}")
            self._add_paragraph(
                f"[Failed to load image '{image_key}']", font_size=SMALL_SIZE, color=MUTED_GRAY, align="center"
            )

    def _save(self) -> BytesIO:
        """Save document to BytesIO buffer."""
        buffer = BytesIO()
        self.document.save(buffer)
        buffer.seek(0)
        return buffer


class GelAnalysisReportBuilder(BaseReportBuilder):
    """
    Generates comprehensive Word document for Gel Analysis reports
    using python-docx with GSKPrecision font family.
    """

    def __init__(self, data: ReportData, images: dict):
        """
        Initialize the report builder.

        Args:
            data: ReportData instance with all structured report data
            images: Dictionary of image_key -> bytes (decoded base64)
        """
        self.data = data
        self.images = images
        super().__init__()

    def add_cover_page(self):
        """Add cover page with GSK logo."""
        try:
            # GSK logo (top-right)
            logo_path = Path(__file__).resolve().parents[3] / GSK_LOGO_PATH
            if logo_path.exists():
                paragraph = self.document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                run = paragraph.add_run()
                run.add_picture(str(logo_path), width=Inches(1.5))
        except Exception as e:
            logger.warning(f"Failed to add GSK logo: {e}")

        # Spacing
        for _ in range(2):
            self.document.add_paragraph()

        # Title
        self._add_paragraph(
            "GEL ANALYSIS REPORT",
            font_size=TITLE_SIZE,
            bold=True,
            color=GSK_ORANGE,
            align="center",
            font_name=HEADING_FONT,
        )

        self.document.add_paragraph()

        # Analysis name
        self._add_paragraph(self.data.analysis_name, font_size=20, bold=True, align="center", font_name=HEADING_FONT)

        # Gel type
        self._add_paragraph(self.data.gel_type, font_size=14, align="center")

        for _ in range(2):
            self.document.add_paragraph()

        # Summary stats
        self._add_paragraph(
            f"Lanes: {self.data.total_lanes_count} | "
            f"Bands: {self.data.total_bands_count} | "
            f"Status: {self.data.analysis_status}",
            font_size=12,
            align="center",
            color=MUTED_GRAY,
        )

        for _ in range(5):
            self.document.add_paragraph()

        # Generated info
        self._add_paragraph(
            f"Generated: {self.data.report_generated_at}", font_size=SMALL_SIZE, align="center", color=MUTED_GRAY
        )

        self._add_paragraph(
            f"Generated by: {self.data.report_generated_by}", font_size=SMALL_SIZE, align="center", color=MUTED_GRAY
        )

        self.document.add_page_break()

    def add_analysis_overview(self):
        """Add analysis overview section."""
        try:
            self._add_section_heading("1. ANALYSIS OVERVIEW")

            data = [
                ("Analysis Name", self.data.analysis_name),
                ("Status", self.data.analysis_status),
                ("Gel Type", self.data.gel_type),
                ("Image", self.data.image_title),
                ("Analyst", self.data.created_by_name),
                ("Date", self.data.created_at),
                ("Total Lanes", str(self.data.total_lanes_count)),
                ("Total Bands", str(self.data.total_bands_count)),
            ]

            if self.data.notes:
                data.append(("Notes", self.data.notes[:500] + "..." if len(self.data.notes) > 500 else self.data.notes))

            self._add_info_table(data, widths=[2.5, 4.5])

        except Exception as e:
            logger.error(f"Error in add_analysis_overview: {e}")

    def add_lane_summary_table(self):
        """Add lane summary table."""
        try:
            self._add_section_heading("2. LANE SUMMARY")

            if not self.data.lanes:
                self._add_paragraph("No lanes detected.", font_size=SMALL_SIZE)
                return

            headers = ["#", "Sample", "Type", "Condition", "Load (µg)", "Purity (%)", "Total Area", "Bands", "Notes"]

            rows = []
            for lane in self.data.lanes:
                purity_str = f"{lane.poi_percentage:.1f}" if lane.poi_percentage is not None else "-"
                total_area_str = f"{lane.total_integrated_area:.0f}" if lane.total_integrated_area is not None else "-"
                load_str = f"{lane.protein_load_ug:.1f}" if lane.protein_load_ug is not None else "-"
                notes_str = lane.notes[:50] + "..." if len(lane.notes) > 50 else lane.notes

                rows.append(
                    [
                        str(lane.lane_number),
                        lane.sample_name,
                        lane.lane_type,
                        lane.condition or "-",
                        load_str,
                        purity_str,
                        total_area_str,
                        str(len(lane.bands)),
                        notes_str or "-",
                    ]
                )

            self._add_data_table(headers, rows)

        except Exception as e:
            logger.error(f"Error in add_lane_summary_table: {e}")

    def add_calibration_section(self):
        """Add MW calibration section."""
        try:
            if not self.data.has_calibration:
                return

            self._add_section_heading("3. MW CALIBRATION")

            # Multi-ladder info
            if self.data.multi_ladder_enabled:
                self._add_paragraph(
                    f"Multi-ladder calibration enabled using {self.data.multi_ladder_template} "
                    f"with {self.data.multi_ladder_interpolation} interpolation for gel smile correction.",
                    font_size=SMALL_SIZE,
                )
                self.document.add_paragraph()

            # Each calibration
            for _i, cal in enumerate(self.data.calibrations, 1):
                if len(self.data.calibrations) > 1:
                    self._add_section_heading(f"Ladder Lane {cal.ladder_lane_number}", level=3)
                else:
                    self._add_section_heading(f"Ladder Lane {cal.ladder_lane_number}", level=2)

                data = [
                    ("Template", cal.template_name),
                    ("Manufacturer", cal.manufacturer),
                    ("Method", cal.method),
                    ("Equation", cal.equation),
                    ("R²", f"{cal.r_squared:.4f} ({cal.r_squared_quality})"),
                    ("Matched Bands", str(cal.matched_band_count)),
                ]

                self._add_info_table(data, widths=[2.0, 5.0])

        except Exception as e:
            logger.error(f"Error in add_calibration_section: {e}")

    def add_gel_image_section(self):
        """Add gel image overview section."""
        try:
            self._add_section_heading("4. GEL IMAGE")

            self._add_captured_image("gel_overview")

            self.document.add_page_break()

        except Exception as e:
            logger.error(f"Error in add_gel_image_section: {e}")

    def add_lane_detail_sections(self):
        """Add individual lane analysis sections."""
        try:
            self._add_section_heading("5. INDIVIDUAL LANE ANALYSIS")

            for lane in self.data.lanes:
                self._add_lane_detail(lane)

        except Exception as e:
            logger.error(f"Error in add_lane_detail_sections: {e}")

    def _add_lane_detail(self, lane: LaneReportData):
        """
        Add detailed analysis for a single lane.

        Args:
            lane: LaneReportData instance
        """
        try:
            # Heading
            self._add_section_heading(f"Lane {lane.lane_number}: {lane.sample_name}", level=2)

            # Lane info table
            purity_str = f"{lane.poi_percentage:.1f}%" if lane.poi_percentage is not None else "N/A"
            total_area_str = f"{lane.total_integrated_area:.0f}" if lane.total_integrated_area is not None else "N/A"
            load_str = (
                f"{lane.protein_load_ug:.2f} µg ({lane.protein_load_type})"
                if lane.protein_load_ug is not None
                else "N/A"
            )

            data = [
                ("Lane Type", lane.lane_type),
                ("Sample", lane.sample_name),
                ("Condition", lane.condition or "N/A"),
                ("Protein Load", load_str),
                ("Purity", purity_str),
                ("Total Integrated Area", total_area_str),
            ]

            if lane.notes:
                data.append(("Notes", lane.notes))

            self._add_info_table(data, widths=[2.0, 5.0])

            # Band data table
            if lane.bands:
                self._add_paragraph("Band Densitometry:", font_size=SMALL_SIZE, bold=True)

                headers = ["#", "Type", "MW (kDa)", "Area", "% Lane", "% Gel", "R²", "Quality"]

                rows = []
                for band in lane.bands:
                    band_num = str(band.band_number) if band.band_number else "-"
                    mw_str = f"{band.estimated_mw_kda:.1f}" if band.estimated_mw_kda is not None else "-"
                    area_str = f"{band.corrected_area:.0f}" if band.corrected_area is not None else "-"
                    pct_lane_str = (
                        f"{band.relative_percent_lane:.1f}" if band.relative_percent_lane is not None else "-"
                    )
                    pct_gel_str = f"{band.relative_percent_gel:.1f}" if band.relative_percent_gel is not None else "-"
                    r2_str = f"{band.fit_r_squared:.3f}" if band.fit_r_squared is not None else "-"
                    quality_str = band.fit_quality or "-"

                    rows.append(
                        [band_num, band.band_type, mw_str, area_str, pct_lane_str, pct_gel_str, r2_str, quality_str]
                    )

                self._add_data_table(headers, rows)

            # Add visualizations
            lane_num = lane.lane_number

            # 2D Electropherogram
            self._add_paragraph("2D Electropherogram:", font_size=SMALL_SIZE, bold=True)
            self._add_captured_image(f"lane_{lane_num}_electropherogram_2d")

            # 3D Terrain
            self._add_paragraph("3D Terrain View:", font_size=SMALL_SIZE, bold=True)
            self._add_captured_image(f"lane_{lane_num}_electropherogram_3d", width=IMAGE_HALF_WIDTH)

            # Digital Lane
            self._add_paragraph("Digital Lane View:", font_size=SMALL_SIZE, bold=True)
            self._add_captured_image(f"lane_{lane_num}_digital_lane", width=IMAGE_DIGITAL_LANE_WIDTH)

            # Spacing before next lane
            self.document.add_paragraph()

        except Exception as e:
            logger.error(f"Error in _add_lane_detail for lane {lane.lane_number}: {e}")

    def add_materials_and_methods(self):
        """Add materials and methods section."""
        try:
            self.document.add_page_break()

            self._add_section_heading("6. MATERIALS AND METHODS")

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
            logger.error(f"Error in add_materials_and_methods: {e}")

    def add_metadata_footer(self):
        """Add metadata footer."""
        try:
            self.document.add_paragraph()

            self._add_paragraph("---", font_size=8, align="center", color=MUTED_GRAY)

            self._add_paragraph(
                f"Report generated: {self.data.report_generated_at}", font_size=8, align="center", color=MUTED_GRAY
            )

            self._add_paragraph(
                f"Generated by: {self.data.report_generated_by}", font_size=8, align="center", color=MUTED_GRAY
            )

            self._add_paragraph(
                f"Software: {self.data.software_version}", font_size=8, align="center", color=MUTED_GRAY
            )

        except Exception as e:
            logger.error(f"Error in add_metadata_footer: {e}")

    def build(self) -> BytesIO:
        """
        Build the complete Word document.

        Returns:
            BytesIO buffer containing the Word document
        """
        logger.info(f"Building Gel Analysis Word report for {self.data.analysis_name}")

        try:
            self.add_cover_page()
        except Exception as e:
            logger.error(f"Failed to add cover page: {e}")

        try:
            self.add_analysis_overview()
        except Exception as e:
            logger.error(f"Failed to add analysis overview: {e}")

        try:
            self.add_lane_summary_table()
        except Exception as e:
            logger.error(f"Failed to add lane summary: {e}")

        try:
            self.add_calibration_section()
        except Exception as e:
            logger.error(f"Failed to add calibration section: {e}")

        try:
            self.add_gel_image_section()
        except Exception as e:
            logger.error(f"Failed to add gel image section: {e}")

        try:
            self.add_lane_detail_sections()
        except Exception as e:
            logger.error(f"Failed to add lane details: {e}")

        try:
            self.add_materials_and_methods()
        except Exception as e:
            logger.error(f"Failed to add materials and methods: {e}")

        try:
            self.add_metadata_footer()
        except Exception as e:
            logger.error(f"Failed to add metadata footer: {e}")

        logger.info(f"Gel Analysis Word report built successfully for {self.data.analysis_name}")
        return self._save()
