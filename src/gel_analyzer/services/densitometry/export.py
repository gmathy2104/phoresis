"""
Export utilities for densitometry results.

Provides CSV and future PDF export functionality for densitometry data.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import GelAnalysis

from .models import DensitometryAnalysisResult, LaneDensitometryResultData

logger = get_logger(__name__)


class DensitometryExporter:
    """
    Export densitometry results to various formats.

    Currently supports CSV export. PDF export planned for future phase.

    Usage:
        exporter = DensitometryExporter()
        csv_content = exporter.export_csv(result, analysis)
    """

    def export_csv(
        self,
        result: DensitometryAnalysisResult,
        analysis: GelAnalysis,
        include_profile: bool = False,
    ) -> str:
        """
        Export densitometry results to CSV format.

        Args:
            result: DensitometryAnalysisResult to export.
            analysis: GelAnalysis model for metadata.
            include_profile: Whether to include profile data.

        Returns:
            CSV content as string.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header section
        writer.writerow(["# Gel Densitometry Analysis Report"])
        writer.writerow(["# Generated", datetime.now().isoformat()])
        writer.writerow(["# Analysis ID", str(analysis.id)])
        writer.writerow(["# Analysis Name", analysis.name])
        writer.writerow(["# Image", analysis.gel_image.title if analysis.gel_image else "N/A"])
        writer.writerow([])

        # Summary section
        writer.writerow(["# Summary"])
        writer.writerow(["Lanes Processed", result.lanes_processed])
        writer.writerow(["Lanes Successful", result.lanes_successful])
        writer.writerow(["Total Bands", result.total_bands])
        writer.writerow(["Gel Total Area", f"{result.gel_total_area:.2f}"])
        if result.average_poi_percentage:
            writer.writerow(["Average Purity (%)", f"{result.average_poi_percentage:.2f}"])
        writer.writerow([])

        # Parameters section
        if result.params_used:
            writer.writerow(["# Parameters"])
            params = result.params_used.to_dict()
            for key, value in params.items():
                writer.writerow([key, value])
            writer.writerow([])

        # Lane summary table
        writer.writerow(["# Lane Summary"])
        writer.writerow(
            [
                "Lane Number",
                "Lane Type",
                "Total Area",
                "POI Area",
                "Other Area",
                "Purity (%)",
                "Band Count",
                "POI Bands",
            ]
        )

        for lane in result.lanes:
            writer.writerow(
                [
                    lane.lane_number,
                    lane.lane_type,
                    f"{lane.total_integrated_area:.2f}",
                    f"{lane.poi_integrated_area:.2f}" if lane.poi_integrated_area else "",
                    f"{lane.other_integrated_area:.2f}" if lane.other_integrated_area else "",
                    f"{lane.poi_percentage:.2f}" if lane.poi_percentage else "",
                    lane.bands_processed,
                    sum(1 for p in lane.peaks if p.band_type == "POI"),
                ]
            )

        writer.writerow([])

        # Band details table
        writer.writerow(["# Band Details"])
        writer.writerow(
            [
                "Lane",
                "Band ID",
                "Band Type",
                "Position Y",
                "MW (kDa)",
                "Peak Center",
                "Amplitude",
                "Sigma",
                "FWHM",
                "Corrected Area",
                "R-squared",
                "SNR",
                "% Lane",
                "% Gel",
                "Fit Quality",
            ]
        )

        for lane in result.lanes:
            for peak in lane.peaks:
                writer.writerow(
                    [
                        lane.lane_number,
                        peak.band_id,
                        peak.band_type,
                        peak.position_y,
                        f"{peak.estimated_mw_kda:.1f}" if peak.estimated_mw_kda else "",
                        f"{peak.peak_center:.2f}" if peak.fit_successful else "",
                        f"{peak.amplitude:.2f}" if peak.fit_successful else "",
                        f"{peak.sigma:.2f}" if peak.fit_successful else "",
                        f"{peak.fwhm:.2f}" if peak.fit_successful else "",
                        f"{peak.corrected_area:.2f}",
                        f"{peak.fit_r_squared:.4f}" if peak.fit_successful else "",
                        f"{peak.snr:.2f}" if peak.snr else "",
                        f"{peak.relative_percent_lane:.2f}" if peak.relative_percent_lane else "",
                        f"{peak.relative_percent_gel:.2f}" if peak.relative_percent_gel else "",
                        peak.fit_quality,
                    ]
                )

        if include_profile:
            writer.writerow([])
            writer.writerow(["# Profile Data"])
            self._write_profile_data(writer, result)

        return output.getvalue()

    def _write_profile_data(
        self,
        writer: csv.writer,
        result: DensitometryAnalysisResult,
    ) -> None:
        """
        Write profile data to CSV.

        Args:
            writer: CSV writer.
            result: Analysis result with profile data.
        """
        for lane in result.lanes:
            if not lane.profile_data:
                continue

            writer.writerow([f"# Lane {lane.lane_number} Profile"])
            writer.writerow(["Y Position", "Intensity", "MW (kDa)", "Background", "Raw"])

            profile = lane.profile_data
            for i in range(len(profile.y_positions)):
                writer.writerow(
                    [
                        profile.y_positions[i],
                        f"{profile.intensities[i]:.2f}",
                        f"{profile.mw_values[i]:.2f}" if profile.mw_values[i] else "",
                        f"{profile.background[i]:.2f}" if i < len(profile.background) else "",
                        f"{profile.raw_intensities[i]:.2f}" if i < len(profile.raw_intensities) else "",
                    ]
                )

            writer.writerow([])

    def export_lane_csv(
        self,
        lane_result: LaneDensitometryResultData,
        analysis_name: str = "",
    ) -> str:
        """
        Export a single lane's densitometry results to CSV.

        Args:
            lane_result: Lane densitometry result.
            analysis_name: Optional analysis name for header.

        Returns:
            CSV content as string.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([f"# Lane {lane_result.lane_number} Densitometry"])
        if analysis_name:
            writer.writerow(["# Analysis", analysis_name])
        writer.writerow(["# Generated", datetime.now().isoformat()])
        writer.writerow([])

        # Lane summary
        writer.writerow(["Lane Type", lane_result.lane_type])
        writer.writerow(["Total Area", f"{lane_result.total_integrated_area:.2f}"])
        if lane_result.poi_percentage:
            writer.writerow(["Purity (%)", f"{lane_result.poi_percentage:.2f}"])
        writer.writerow(["Band Count", lane_result.bands_processed])
        writer.writerow([])

        # Band table
        writer.writerow(
            [
                "Band ID",
                "Type",
                "Position Y",
                "MW (kDa)",
                "Corrected Area",
                "% Lane",
                "Fit Quality",
            ]
        )

        for peak in lane_result.peaks:
            writer.writerow(
                [
                    peak.band_id,
                    peak.band_type,
                    peak.position_y,
                    f"{peak.estimated_mw_kda:.1f}" if peak.estimated_mw_kda else "",
                    f"{peak.corrected_area:.2f}",
                    f"{peak.relative_percent_lane:.2f}" if peak.relative_percent_lane else "",
                    peak.fit_quality,
                ]
            )

        return output.getvalue()


def generate_csv_filename(analysis: GelAnalysis) -> str:
    """
    Generate a filename for CSV export.

    Args:
        analysis: GelAnalysis model.

    Returns:
        Filename string.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = analysis.name.replace(" ", "_")[:30] if analysis.name else "analysis"
    return f"densitometry_{name}_{timestamp}.csv"
