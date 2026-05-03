"""
Calibration service package for MW estimation from ladder lanes.

This package provides:
- CalibrationService: Main orchestrator for single-ladder calibration
- MultiLadderCalibrationService: Position-aware multi-ladder interpolation
- CalibrationParams: Configurable parameters for calibration
- CalibrationResult: Result dataclass with coefficients and statistics
- BandMatch: Represents a matched band with Rf and residual
- LadderCalibrationData: Data container for interpolation
- InterpolatedMWResult: Result of multi-ladder MW estimation

Usage:
    from gel_analyzer.services.calibration import (
        CalibrationService,
        MultiLadderCalibrationService,
        CalibrationParams,
        CalibrationResult,
        BandMatch,
    )

    # Single-ladder calibration
    service = CalibrationService(params)
    matches = service.match_bands_to_template(lane, template)
    result = service.calibrate(lane, template, matches)

    # Multi-ladder calibration (gel smile correction)
    multi_service = MultiLadderCalibrationService(analysis)
    result = multi_service.calibrate_all_ladders(template, user)
    mw = multi_service.estimate_mw_at_position(y, x, top, bottom)
"""

from .models import (
    BandMatch,
    CalibrationParams,
    CalibrationResult,
    InterpolatedMWResult,
    InterpolationMethodType,
    InterpolationWeight,
    # Multi-ladder dataclasses
    LadderCalibrationData,
    MultiLadderCalibrationResult,
)
from .multi_ladder_service import MultiLadderCalibrationService
from .service import CalibrationService

__all__ = [
    # Single-ladder calibration
    "CalibrationService",
    "CalibrationParams",
    "CalibrationResult",
    "BandMatch",
    # Multi-ladder calibration
    "MultiLadderCalibrationService",
    "LadderCalibrationData",
    "InterpolationWeight",
    "InterpolatedMWResult",
    "MultiLadderCalibrationResult",
    "InterpolationMethodType",
]
