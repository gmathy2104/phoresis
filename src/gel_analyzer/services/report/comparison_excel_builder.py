"""
Excel workbook builder for gel lane comparison reports.

Generates multi-sheet .xlsx files with the Phoresis palette using openpyxl.
"""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from phoresis_core.logging_config import get_logger

from .comparison_data_collector import ComparisonReportData
from .constants import PHORESIS_LOGO_PATH, TABLE_HEADER_BG
from .page_rows import cell_text, mean_purity_text, sample_text

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

# The number format of a readout column (page_rows: ``readout_numbers``), at the page's decimals; every other
# value is a % or a kDa, "0.0" (as the densitometry workbook).
_NUMBER_FORMATS = {"bands": "0", "band_count": "0", "hcp_total_signal": "#,##0"}
# A readout's sheet (an Excel sheet name holds no "/"), by readout; a kind that measures nothing has none.
_READOUT_SHEETS = {"PURITY": "POI Purity", "MOLECULE_VARIANTS": "HMWS-Main-LMWS", "HOST_CELL_PROTEINS": "HCP"}
# The page columns that are not the readout's values: the readout sheets leave them to the Sample Summary.
_NOT_VALUE_COLUMNS = {"bands", "poi_kda"}

# Sections that are image-only and not applicable to Excel
_EXCEL_SKIP_SECTIONS = {"digital_gel", "gel_images", "materials_methods"}


class ComparisonExcelBuilder:
    """
    Generates a multi-sheet Excel workbook for Lane Comparison reports.

    Sheets created based on selected sections:
    - Overview: key-value metadata
    - Sample Summary: one row per lane
    - Band Comparison: MW-clustered rows
    - Lane Details: all bands with densitometry
    - POI Purity: purity table + embedded chart
    """

    def __init__(
        self,
        data: ComparisonReportData,
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
        title_cell.value = "LANE COMPARISON REPORT"
        title_cell.font = _TITLE_FONT

        ws.merge_cells("A4:C4")
        ws["A4"].value = self.data.name
        ws["A4"].font = Font(name="Inter", bold=True, size=13)

        # Key-value pairs
        calibration_status = (
            f"All lanes calibrated ({self.data.calibrated_count})"
            if self.data.all_calibrated
            else f"{self.data.calibrated_count} of {self.data.lane_count} lanes calibrated"
        )

        rows = [
            ("Description", self.data.description or "N/A"),
            ("Lane Count", self.data.lane_count),
            ("Assays", ", ".join(kind.label for kind in self.data.kinds) or "None"),
            ("Calibration", calibration_status),
        ]
        # The mean purity of each purity kind, over the lanes compared (services/mean_purity.py).
        rows += [(f"Mean purity · {kind.label}", mean_purity_text(kind.mean)) for kind in self.data.kinds if kind.mean]
        rows += [
            ("Created By", self.data.created_by_name),
            ("Created Date", self.data.created_at),
            ("Public", "Yes" if self.data.is_public else "No"),
            ("Generated At", self.data.report_generated_at),
            ("Generated By", self.data.report_generated_by),
        ]

        start_row = 6
        for i, (label, value) in enumerate(rows):
            r = start_row + i
            ws.cell(row=r, column=1, value=label).font = _LABEL_FONT
            ws.cell(row=r, column=2, value=value).font = _BODY_FONT

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
        """Every lane in one sheet, its kind (assay) named, and the readout columns of every kind side by side: a lane
        fills its own kind's columns with the comparison page's values (page_rows), never a purity for a western."""
        ws = self.wb.create_sheet("Sample Summary")

        columns = list({column["key"]: column for kind in self.data.kinds for column in kind.columns}.values())
        headers = ["#", "Sample", "Source Analysis", "Assay", "Lane #", "Condition", "Load (µg)"]
        headers += [column["label"] for column in columns] + ["Notes", "Saturated bands"]
        self._write_header_row(ws, headers)

        for i, lane in enumerate(self.data.lanes, 1):
            r = i + 1
            load_str = ""
            if lane.protein_load_ug is not None:
                load_str = f"{lane.protein_load_ug:.1f}"
                if lane.protein_load_type:
                    load_str += f" ({lane.protein_load_type})"
            kind = self.data.kind_of(lane)

            own = [
                i,
                sample_text(lane) + (" (REF)" if lane.is_reference else ""),
                lane.analysis_name,
                kind.label if kind else lane.gel_type,
                lane.lane_number,
                lane.condition or "",
                load_str,
            ]
            for j, val in enumerate(own, 1):
                cell = ws.cell(row=r, column=j, value=val)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER
            for j, column in enumerate(columns, len(own) + 1):
                if kind is not None and any(c["key"] == column["key"] for c in kind.columns):
                    self._write_readout_cell(ws, r, j, lane, column["key"])
                else:
                    ws.cell(row=r, column=j).border = _THIN_BORDER
            for j, val in enumerate([lane.notes or "", ", ".join(lane.saturated_bands)], len(own) + len(columns) + 1):
                cell = ws.cell(row=r, column=j, value=val)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER

        self._auto_width(ws, headers)

    def _add_band_comparison_sheet(self):
        ws = self.wb.create_sheet("Band Comparison")

        # Cluster bands (reuse logic from Word builder)
        clusters = self._cluster_bands_by_mw(self.data.mw_tolerance_pct)
        if not clusters:
            ws.cell(row=1, column=1, value="No calibrated bands for MW comparison.").font = _BODY_FONT
            return

        headers = ["MW (kDa)"] + [sample_text(lane)[:25] for lane in self.data.lanes]
        self._write_header_row(ws, headers)

        for i, cluster in enumerate(clusters):
            r = i + 2
            ws.cell(row=r, column=1, value=round(cluster["mw"], 1)).font = _BOLD_FONT
            ws.cell(row=r, column=1).border = _THIN_BORDER

            for lane_idx in range(len(self.data.lanes)):
                band = cluster["bands"].get(lane_idx)
                val = ""
                if band and band["pct_lane"] is not None:
                    val = f"{band['pct_lane']:.1f}%"
                cell = ws.cell(row=r, column=lane_idx + 2, value=val)
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
        """One sheet per kind (assay) with a readout: its lanes with the page's values, and the kind's chart."""
        from .readout_chart import render_readout_chart

        used = set()
        for kind in self.data.kinds:
            name = _READOUT_SHEETS.get(kind.readout)
            if name is None:
                continue
            # Two kinds of one readout (two anti-molecule assays) get two sheets.
            sheet, n = name, 2
            while sheet in used:
                sheet, n = f"{name} {n}", n + 1
            used.add(sheet)
            ws = self.wb.create_sheet(sheet)

            columns = [column for column in kind.columns if column["key"] not in _NOT_VALUE_COLUMNS]
            is_purity = kind.readout == "PURITY"
            headers = ["Sample", "Assay"] + [column["label"] for column in columns] + (["Status"] if is_purity else [])
            self._write_header_row(ws, headers)

            for r, lane in enumerate(kind.lanes, 2):
                for j, val in enumerate([sample_text(lane) + (" (REF)" if lane.is_reference else ""), kind.label], 1):
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
                mean = None
                if kind.mean is not None and kind.mean.value is not None:
                    mean = (kind.mean.value, f"Mean {mean_purity_text(kind.mean)}")
                chart_buf = render_readout_chart(
                    kind.readout, kind.lanes, mean=mean, figsize=(7, 3.5), dpi=120, dark_theme=False
                )
                if chart_buf:
                    img = XlImage(chart_buf)
                    img.width = 600
                    img.height = 300
                    ws.add_image(img, f"A{len(kind.lanes) + 4}")
            except Exception as e:
                logger.warning(f"Failed to embed the readout chart in Excel: {e}")

    def _add_quantification_sheet(self):
        """Per-analysis protein-quantification calibration summary (no curve)."""
        data = self.data
        if not data.has_quantification or not data.analysis_quant_summaries:
            return

        ws = self.wb.create_sheet("Quantification")
        names = {}
        for lane in data.lanes:
            names.setdefault(lane.analysis_id, lane.analysis_name)

        headers = ["Analysis", "Method", "Unit", "Equation", "R²", "Quality"]
        self._write_header_row(ws, headers)

        r = 2
        for aid, s in data.analysis_quant_summaries.items():
            vals = [
                names.get(aid, aid),
                s["method"],
                s["unit"],
                s["equation"],
                s["r_squared"],
                s["r_squared_quality"],
            ]
            for j, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=j, value=v)
                cell.font = _BODY_FONT
                cell.border = _THIN_BORDER
            r += 1

        self._auto_width(ws, headers)

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

    def _cluster_bands_by_mw(self, tolerance_pct: float) -> list:
        """Cluster bands across lanes by MW (same algorithm as Word builder)."""
        all_bands = []
        for lane_idx, lane in enumerate(self.data.lanes):
            for band in lane.bands:
                if band.estimated_mw_kda and band.estimated_mw_kda > 0:
                    all_bands.append(
                        {
                            "lane_idx": lane_idx,
                            "mw": band.estimated_mw_kda,
                            "pct_lane": band.relative_percent_lane,
                            "band_type": band.band_type,
                        }
                    )

        all_bands.sort(key=lambda b: b["mw"], reverse=True)

        clusters = []
        for band in all_bands:
            merged = False
            for cluster in clusters:
                pct_diff = abs(band["mw"] - cluster["mw"]) / cluster["mw"] * 100
                if pct_diff <= tolerance_pct and band["lane_idx"] not in cluster["bands"]:
                    cluster["bands"][band["lane_idx"]] = band
                    mws = [b["mw"] for b in cluster["bands"].values()]
                    cluster["mw"] = sum(mws) / len(mws)
                    merged = True
                    break
            if not merged:
                clusters.append({"mw": band["mw"], "bands": {band["lane_idx"]: band}})

        clusters.sort(key=lambda c: c["mw"], reverse=True)
        return clusters

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> BytesIO:
        """Build the complete Excel workbook and return as BytesIO."""
        logger.info(f"Building Lane Comparison Excel report for '{self.data.name}'")

        sheet_map = [
            ("overview", self._add_overview_sheet, "overview"),
            ("sample_summary", self._add_sample_summary_sheet, "sample summary"),
            ("band_comparison", self._add_band_comparison_sheet, "band comparison"),
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

        logger.info(f"Lane Comparison Excel report built for '{self.data.name}'")
        return buf
