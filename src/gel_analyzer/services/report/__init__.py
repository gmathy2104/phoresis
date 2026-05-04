"""
Report generation service for gel analyzer.

Exports:
- BaseReportBuilder: Base class with shared Word document utilities
- GelAnalysisReportBuilder: Main report builder class for single analysis
- ComparisonReportBuilder: Report builder for lane comparisons (Word)
- ComparisonExcelBuilder: Report builder for lane comparisons (Excel)
- ComparisonPowerPointBuilder: Report builder for lane comparisons (PowerPoint)
- DensitometryReportBuilder: Report builder for densitometry analysis (Word)
- DensitometryExcelBuilder: Report builder for densitometry analysis (Excel)
- DensitometryPowerPointBuilder: Report builder for densitometry analysis (PowerPoint)
- ReportDataCollector: Data collection and structuring for single analysis
- ComparisonDataCollector: Data collection and structuring for comparisons
- DensitometryDataCollector: Data collection and structuring for densitometry
- render_poi_purity_chart: Shared POI purity bar chart renderer
- render_terrain_chart: 3D terrain chart renderer for densitometry
"""

from .builder import BaseReportBuilder, GelAnalysisReportBuilder
from .comparison_builder import ComparisonReportBuilder
from .comparison_data_collector import ComparisonDataCollector
from .comparison_excel_builder import ComparisonExcelBuilder
from .comparison_pptx_builder import ComparisonPowerPointBuilder
from .data_collector import ReportDataCollector
from .densitometry_builder import DensitometryReportBuilder
from .densitometry_data_collector import DensitometryDataCollector
from .densitometry_excel_builder import DensitometryExcelBuilder
from .densitometry_pptx_builder import DensitometryPowerPointBuilder
from .poi_purity_chart import render_poi_purity_chart
from .terrain_chart import render_terrain_chart

__all__ = [
    "BaseReportBuilder",
    "GelAnalysisReportBuilder",
    "ComparisonReportBuilder",
    "ComparisonExcelBuilder",
    "ComparisonPowerPointBuilder",
    "DensitometryReportBuilder",
    "DensitometryExcelBuilder",
    "DensitometryPowerPointBuilder",
    "ReportDataCollector",
    "ComparisonDataCollector",
    "DensitometryDataCollector",
    "render_poi_purity_chart",
    "render_terrain_chart",
]
