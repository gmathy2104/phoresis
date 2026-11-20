"""
Excel workbook builder for densitometry reports.

Generates multi-sheet .xlsx files with the Phoresis palette using openpyxl.
"""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from phoresis_core.logging_config import get_logger

from .constants import (
    PHORESIS_LOGO_PATH,
    TABLE_HEADER_BG,
    calibration_range_display,
    is_outside_calibration_range,
)
from .densitometry_data_collector import DensitometryReportData
from .page_rows import card_text, cell_text, readout_card, sample_text

logger = get_logger(__name__)

# Brand palette for Excel (Phoresis accent-600)
_ACCENT_HEX = TABLE_HEADER_BG  # "2563EB"
_HEADER_FILL = PatternFill(start_color=_ACCENT_HEX, end_color=_ACCENT_HEX, fill_type="solid")
_HEADER_FONT = Font(name="Inter", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="Inter", size=10)
_BOLD_FONT = Font(name="Inter", bold=True, size=10)
_TITLE_FONT = Font(name="Inter", bold=True, size=16, color=_ACCENT_HEX)
_LABEL_FONT = Font(name="Inter", bold=True, size=10, color="6C757D")
_THIN_BORDER = Border(
    left=Side(style="thin", color="D0D0D0"),
    right=Side(style="thin", color="D0D0D0"),
    top=Side(style="thin", color="D0D0D0"),
    bottom=Side(style="thin", color="D0D0D0"),
)
# Light-red fill for out-of-spec QC recovery rows (Table B)
_OUT_OF_SPEC_FILL = PatternFill(start_color="FCE4E4", end_color="FCE4E4", fill_type="solid")

# Sections that are image-only and not applicable to Excel
_EXCEL_SKIP_SECTIONS = {"gel_image", "digital_gel", "terrain_view", "materials_methods"}

# The number format of a readout column (page_rows: ``readout_numbers``), at the page's decimals; every other
# value is a % or a kDa, "0.0".
_NUMBER_FORMATS = {"bands": "0", "band_count": "0", "hcp_total_signal": "#,##0"}
# The readout's sheet, by readout (an Excel sheet name holds no "/"); a gel that measures nothing has none.
_READOUT_SHEETS = {"PURITY": "POI Purity", "MOLECULE_VARIANTS": "HMWS-Main-LMWS", "HOST_CELL_PROTEINS": "HCP"}
# The page columns that are not the readout's values: the readout sheet leaves them to the Sample Summary.
_NOT_VALUE_COLUMNS = {"bands", "poi_kda", "measured"}


class DensitometryExcelBuilder:
    """
    Generates a multi-sheet Excel workbook for Densitometry reports.

    Sheets created based on selected sections:
    - Overview: key-value metadata
    - Sample Summary: one row per lane
    - Lane Details: all bands with densitometry
    - POI Purity: purity table + embedded chart
    """

    def __init__(
        self,
        data: DensitometryReportData,
        sections: list[str] | None = None,
        band_overlay: bool = True,
    ):
        self.data = data
        self.sections = sections
        self.band_overlay = band_overlay  # not used in Excel, kept for API consistency
        self.wb = Workbook()
        # Remove default sheet — we'll create our own
        self.wb.remove(self.wb.active)

    def _should_include(self, section_key: str) -> bool:
        if section_key in _EXCEL_SKIP_SECTIONS:
            return False
        if self.sections is None:
            return True
        return section_key in self.sections

    # ── Sheet builders ────────────────────────────────────────────

    def _add_overview_sheet(self):
        ws = self.wb.create_sheet("Overview")

        # Logo
        try:
            logo_path = Path(__file__).resolve().parents[3] / PHORESIS_LOGO_PATH
            # No logo is configured (an empty path is the source folder itself, never an image).
            if PHORESIS_LOGO_PATH and logo_path.is_file():
                img = XlImage(str(logo_path))
                img.width = 160
                img.height = 50
                ws.add_image(img, "D1")
        except Exception as e:
            logger.warning(f"Failed to add logo to Excel: {e}")

        # Title
        ws.merge_cells("A3:C3")
        title_cell = ws["A3"]
        title_cell.value = "DENSITOMETRY ANALYSIS REPORT"
        title_cell.font = _TITLE_FONT

        ws.merge_cells("A4:C4")
        ws["A4"].value = self.data.analysis_name
        ws["A4"].font = Font(name="Inter", bold=True, size=13)

        # Key-value pairs
        # The page's readout card (Mean purity, Main band (mean), HCP reference) stands for the readout.
        card = readout_card(self.data.cards)
        readout_row = (
            (card["label"], card_text(card)) if card is not None else ("Average Purity", self.data.average_purity_text)
        )
        rows = [
            ("Assay", self.data.assay_label),
            ("Gel Type", self.data.gel_type),
            ("Image", self.data.image_title),
            ("Status", self.data.analysis_status + (f" — {self.data.status_hint}" if self.data.status_hint else "")),
            ("Total Lanes", self.data.total_lanes_count),
            ("Total Bands", self.data.total_bands_count),
            readout_row,
            ("Densitometry Computed", self.data.densitometry_computed_at or "N/A"),
            ("Analyst", self.data.created_by_name),
            ("Created Date", self.data.created_at),
            ("Generated At", self.data.report_generated_at),
            ("Generated By", self.data.report_generated_by),
        ]

        start_row = 6
        for i, (label, value) in enumerate(rows):
            r = start_row + i
            ws.cell(row=r, column=1, value=label).font = _LABEL_FONT
            ws.cell(row=r, column=2, value=value).font = _BODY_FONT

        # The page's "To check" items, warnings first, under the facts.
        r = start_row + len(rows) + 1
        ws.cell(row=r, column=1, value="To check").font = _BOLD_FONT
        for check in self.data.checks or [{"level": "", "title": "Nothing to check.", "detail": ""}]:
            r += 1
            ws.cell(
                row=r, column=1, value={"warn": "Warning", "info": "Note"}.get(check["level"], "")
            ).font = _LABEL_FONT
            ws.cell(row=r, column=2, value=check["title"]).font = _BODY_FONT
            ws.cell(row=r, column=3, value=check.get("detail") or "").font = _BODY_FONT

        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 45
        ws.column_dimensions["C"].width = 20

    def _write_readout_cell(self, ws, row, column, lane, key):
        """The page's value of ``key`` for the lane: its number when it has one, else the reason it has none."""
        number = lane.readout_numbers.get(key)
        cell = ws.cell(row=row, column=column, value=number if number is not None else cell_text(lane, key))
        if number is not None:
            cell.number_format = _NUMBER_FORMATS.get(key, "0.0")
        cell.font = _BODY_FONT
        cell.border = _THIN_BORDER

    def _add_sample_summary_sheet(self):
        ws = self.wb.create_sheet("Sample Summary")

        # The lane's own fields, then the readout's columns with the analysis page's values (page_rows).
        columns = self.data.readout_columns
        headers = (
            ["Lane #", "Sample", "Type", "Condition", "Load (µg)"]
            + [column["label"] for column in columns]
            + ["Fit Quality", "Notes", "Saturated bands"]
        )
        self._write_header_row(ws, headers)

        for i, lane in enumerate(self.data.lanes, 1):
            r = i + 1
            load_str = ""
            if lane.protein_load_ug is not None:
                load_str = f"{lane.protein_load_ug:.1f}"
                if lane.protein_load_type:
                    load_str += f" ({lane.protein_load_type})"

            # Compute fit quality: most frequent quality among bands
            fit_quality = ""
            if lane.bands:
                qualities = [b.fit_quality for b in lane.bands if b.fit_quality]
                if qualities:
                    # Get most common quality
                    fit_quality = max(set(qualities), key=qualities.count)

            own = [
                lane.lane_number,
                sample_text(lane) + (" (REF)" if lane.is_reference else ""),
                lane.lane_type,
                lane.condition or "",
                load_str,
            ]
            tail = [
                fit_quality,
                (lane.notes[:50] + "...") if lane.notes and len(lane.notes) > 50 else (lane.notes or ""),
                ", ".join(lane.saturated_bands),  # the page's saturation check (page_rows)
            ]
            for j, val in enumerate(own, 1):
                cell = ws.cell(row=r, column=j, value=val)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER
            for j, column in enumerate(columns, len(own) + 1):
                self._write_readout_cell(ws, r, j, lane, column["key"])
            for j, val in enumerate(tail, len(own) + len(columns) + 1):
                cell = ws.cell(row=r, column=j, value=val)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER

        self._auto_width(ws, headers)

    def _add_lane_details_sheet(self):
        ws = self.wb.create_sheet("Lane Details")

        headers = [
            "Sample",
            "Lane #",
            "Band",
            "Type",
            "MW (kDa)",
            "Corrected Area",
            "% Lane",
            "% Gel",
            "FWHM",
            "R²",
            "Quality",
            "Saturated",
            "Clipped pixels (%)",
        ]
        self._write_header_row(ws, headers)

        row = 2
        for lane in self.data.lanes:
            for band in lane.bands:
                values = [
                    sample_text(lane),
                    lane.lane_number,
                    band.name,  # "B3", as the page names it
                    band.band_type,
                    round(band.estimated_mw_kda, 1) if band.estimated_mw_kda else "",
                    round(band.corrected_area, 0) if band.corrected_area else "",
                    round(band.relative_percent_lane, 1) if band.relative_percent_lane is not None else "",
                    round(band.relative_percent_gel, 1) if band.relative_percent_gel is not None else "",
                    round(band.fwhm, 2) if band.fwhm else "",
                    round(band.fit_r_squared, 3) if band.fit_r_squared else "",
                    band.fit_quality or "",
                    {True: "Yes", False: "No"}.get(band.saturated, ""),
                    (
                        round(band.saturated_pixel_fraction * 100, 2)
                        if band.saturated_pixel_fraction is not None
                        else ""
                    ),
                ]
                for j, val in enumerate(values, 1):
                    cell = ws.cell(row=row, column=j, value=val)
                    cell.font = _BODY_FONT
                    cell.border = _THIN_BORDER
                row += 1

        self._auto_width(ws, headers)

    def _add_poi_purity_sheet(self):
        """The readout's sheet: each lane the readout reads, with the page's values, and the readout's chart."""
        sheet = _READOUT_SHEETS.get(self.data.readout)
        if sheet is None:
            return
        ws = self.wb.create_sheet(sheet)

        columns = [column for column in self.data.readout_columns if column["key"] not in _NOT_VALUE_COLUMNS]
        is_purity = self.data.readout == "PURITY"
        headers = ["Lane #", "Sample"] + [column["label"] for column in columns] + (["Status"] if is_purity else [])
        self._write_header_row(ws, headers)

        read = [lane for lane in self.data.lanes if any(column["key"] in lane.readout_cells for column in columns)]
        for r, lane in enumerate(read, 2):
            for j, val in enumerate([lane.lane_number, sample_text(lane) + (" (REF)" if lane.is_reference else "")], 1):
                cell = ws.cell(row=r, column=j, value=val)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER
            for j, column in enumerate(columns, 3):
                self._write_readout_cell(ws, r, j, lane, column["key"])
            if is_purity:
                purity = lane.readout_numbers.get("purity")
                if purity is None:
                    status = "N/A"
                elif purity >= 90:
                    status = "Pass (Target)"
                elif purity >= 70:
                    status = "Pass (Minimum)"
                else:
                    status = "Below minimum"
                cell = ws.cell(row=r, column=len(columns) + 3, value=status)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER

        self._auto_width(ws, headers)

        # Embed chart image
        try:
            from .readout_chart import render_readout_chart

            mean = None
            if self.data.average_purity is not None:
                mean = (self.data.average_purity, f"Mean {self.data.average_purity_text}")
            chart_buf = render_readout_chart(
                self.data.readout, self.data.lanes, mean=mean, figsize=(7, 3.5), dpi=120, dark_theme=False
            )
            if chart_buf:
                img = XlImage(chart_buf)
                img.width = 600
                img.height = 300
                chart_row = len(read) + 4
                ws.add_image(img, f"A{chart_row}")
        except Exception as e:
            logger.warning(f"Failed to embed the readout chart in Excel: {e}")

    def _add_quantification_sheet(self):
        data = self.data
        if not data.has_quantification or data.quant_calibration is None:
            return
        ws = self.wb.create_sheet("Quantification")
        cal = data.quant_calibration

        # Methodology / metadata block
        meta = [
            ("Method", cal.method),
            ("Unit", cal.unit),
            ("Equation", cal.equation),
            ("R²", f"{cal.r_squared:.4f} ({cal.r_squared_quality})"),
            ("Points used / excluded", f"{cal.n_points} / {cal.n_excluded}"),
            ("Fitted by", f"{cal.created_by_name} on {cal.created_at}"),
            ("Recovery in-spec range", "80–120%"),
        ]
        if cal.last_recomputed_at:
            meta.append(("Auto-recomputed (drift)", cal.last_recomputed_at))
        row = 1
        for label, value in meta:
            ws.cell(row=row, column=1, value=label).font = _LABEL_FONT
            ws.cell(row=row, column=2, value=value).font = _BODY_FONT
            row += 1
        row += 1

        if not data.quant_points:
            ws.cell(
                row=row,
                column=1,
                value="Fit unavailable — calibration data incomplete.",
            ).font = _BODY_FONT
            return

        # Table A — calibration points
        headers_a = ["Lane #", "Load", "Unit", "Corrected area", "Residual %", "Excluded"]
        for j, h in enumerate(headers_a, 1):
            c = ws.cell(row=row, column=j, value=h)
            c.font = _HEADER_FONT
            c.fill = _HEADER_FILL
        row += 1
        for p in data.quant_points:
            vals = [
                p.lane_number,
                p.load_amount,
                p.load_unit,
                p.corrected_area,
                p.residual_pct,
                "Yes" if p.is_excluded else "",
            ]
            for j, v in enumerate(vals, 1):
                ws.cell(row=row, column=j, value=v).font = _BODY_FONT
            row += 1
        row += 1

        # Table B — controls / QC (red fill on out-of-spec rows)
        if data.quant_controls:
            headers_b = ["Lane #", "Known", "Predicted", "Recovery %", "Range", "Flag"]
            for j, h in enumerate(headers_b, 1):
                c = ws.cell(row=row, column=j, value=h)
                c.font = _HEADER_FONT
                c.fill = _HEADER_FILL
            row += 1
            for ctrl in data.quant_controls:
                vals = [
                    ctrl.lane_number,
                    ctrl.known_amount,
                    ctrl.predicted_amount,
                    ctrl.recovery_pct,
                    calibration_range_display(ctrl.calibration_range),
                    "OUT OF SPEC" if ctrl.out_of_spec else "OK",
                ]
                for j, v in enumerate(vals, 1):
                    cell = ws.cell(row=row, column=j, value=v)
                    cell.font = _BODY_FONT
                    if ctrl.out_of_spec:
                        cell.fill = _OUT_OF_SPEC_FILL
                row += 1
            row += 1

        # Table C — sample estimated amounts
        if data.quant_samples:
            headers_c = ["Lane #", "Sample", "Est. amount", "Unit", "Range"]
            for j, h in enumerate(headers_c, 1):
                c = ws.cell(row=row, column=j, value=h)
                c.font = _HEADER_FONT
                c.fill = _HEADER_FILL
            row += 1
            for s in data.quant_samples:
                vals = [
                    s.lane_number,
                    s.sample_name,
                    s.estimated_amount,
                    s.unit,
                    calibration_range_display(s.calibration_range),
                ]
                outside = is_outside_calibration_range(s.calibration_range)
                for j, v in enumerate(vals, 1):
                    cell = ws.cell(row=row, column=j, value=v)
                    cell.font = _BODY_FONT
                    if outside:
                        cell.fill = _OUT_OF_SPEC_FILL
                row += 1

        self._auto_width(ws, headers_a)

    # ── Utilities ─────────────────────────────────────────────────

    def _write_header_row(self, ws, headers):
        for j, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=j, value=h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = _THIN_BORDER

    def _auto_width(self, ws, headers):
        for i, h in enumerate(headers, 1):
            col_letter = get_column_letter(i)
            ws.column_dimensions[col_letter].width = max(len(str(h)) + 4, 12)

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> BytesIO:
        """Build the complete Excel workbook and return as BytesIO."""
        logger.info(f"Building Densitometry Excel report for '{self.data.analysis_name}'")

        sheet_map = [
            ("overview", self._add_overview_sheet, "overview"),
            ("sample_summary", self._add_sample_summary_sheet, "sample summary"),
            ("lane_details", self._add_lane_details_sheet, "lane details"),
            ("poi_purity", self._add_poi_purity_sheet, "POI purity"),
            ("quantification", self._add_quantification_sheet, "quantification"),
        ]

        for key, method, desc in sheet_map:
            if self._should_include(key):
                try:
                    method()
                except Exception as e:
                    logger.error(f"Failed to add Excel sheet '{desc}': {e}")

        # Ensure at least one sheet exists
        if not self.wb.sheetnames:
            self._add_overview_sheet()

        buf = BytesIO()
        self.wb.save(buf)
        buf.seek(0)

        logger.info(f"Densitometry Excel report built for '{self.data.analysis_name}'")
        return buf
