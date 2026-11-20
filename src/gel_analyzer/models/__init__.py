"""
GelAnalyzer models package.

Models:
- GelImage: Uploaded gel electrophoresis images
- GelAnalysis: Analysis sessions for gel images
- Lane: Lane annotations within a gel
- Band: Band annotations within lanes
- MWMarker: Molecular weight markers for calibration
- LadderTemplate: Reusable MW ladder definitions
- LadderBandDefinition: Individual bands in ladder templates
- LadderCalibration: Calibration results linking analysis to templates
- MultiLadderCalibrationConfig: Multi-ladder calibration configuration
- DensitometryResult: Extended densitometry data for bands
- LaneDensitometrySummary: Aggregated densitometry for lanes
- DensitometryJob: Async task tracking for densitometry
"""

from .analysis import GelAnalysis
from .annotations import Band, Lane, MWMarker
from .densitometry import (
    DensitometryJob,
    DensitometryResult,
    LaneDensitometrySummary,
)
from .gel_assay import GelAssay
from .gel_image import GelImage
from .ladder_templates import (
    BandColor,
    CalibrationMethod,
    InterpolationMethod,
    LadderBandDefinition,
    LadderCalibration,
    LadderCategory,
    LadderTemplate,
    MultiLadderCalibrationConfig,
)
from .quantification import ProteinQuantCalibration, ProteinQuantCalibrationPoint
from .saved_comparison import SavedComparison, SavedComparisonLane

__all__ = [
    "GelImage",
    "GelAssay",
    "GelAnalysis",
    "Lane",
    "Band",
    "MWMarker",
    # Ladder calibration models
    "LadderTemplate",
    "LadderBandDefinition",
    "LadderCalibration",
    "LadderCategory",
    "BandColor",
    "CalibrationMethod",
    # Multi-ladder calibration
    "InterpolationMethod",
    "MultiLadderCalibrationConfig",
    # Densitometry models
    "DensitometryResult",
    "LaneDensitometrySummary",
    "DensitometryJob",
    # Saved Comparison models
    "SavedComparison",
    "SavedComparisonLane",
    # Protein quantification models
    "ProteinQuantCalibrationPoint",
    "ProteinQuantCalibration",
]
