"""Dataclasses for the protein quantification calibration service."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Method = Literal["LINEAR", "POLYNOMIAL_2", "FOUR_PL"]
Unit = Literal["UG", "UG_ML"]
Role = Literal["CALIBRATION", "CONTROL"]

# Recovery range for CONTROL points considered in-spec. Outside this range the
# control is flagged out-of-spec in the QC table and on the calibration curve.
# Centralised here so the UI / report layers can read the same constant.
QC_RECOVERY_RANGE = (80.0, 120.0)


@dataclass
class QuantParams:
    method: Method = "LINEAR"
    unit: Unit = "UG"
    excluded_band_ids: list[str] = field(default_factory=list)


@dataclass
class QuantPoint:
    band_id: str
    lane_id: int
    lane_number: int
    role: Role
    load_amount: float | None      # known for CALIBRATION + CONTROL; None for SAMPLE
    load_unit: Unit | None
    corrected_area: float | None   # None if densitometry not yet run
    is_excluded: bool = False
    residual: float | None = None  # filled at fit time
    predicted_amount: float | None = None  # filled at fit time


@dataclass
class QuantResult:
    success: bool
    method: Method = "LINEAR"
    unit: Unit = "UG"
    coefficients: dict = field(default_factory=dict)
    r_squared: float = 0.0
    equation: str = ""
    calibration_points: list[QuantPoint] = field(default_factory=list)
    control_points: list[QuantPoint] = field(default_factory=list)
    sample_projections: list[QuantPoint] = field(default_factory=list)
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "method": self.method,
            "unit": self.unit,
            "coefficients": self.coefficients,
            "r_squared": round(self.r_squared, 6),
            "equation": self.equation,
            "calibration_points": [_pt_to_dict(p) for p in self.calibration_points],
            "control_points":     [_pt_to_dict(p, with_recovery=True) for p in self.control_points],
            "sample_projections": [_pt_to_dict(p, sample=True) for p in self.sample_projections],
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def _pt_to_dict(p: QuantPoint, *, with_recovery: bool = False, sample: bool = False) -> dict:
    base = {
        "band_id": p.band_id,
        "lane_number": p.lane_number,
        "corrected_area": p.corrected_area,
        "is_excluded": p.is_excluded,
    }
    has_load = p.load_amount is not None and p.load_amount != 0
    if not sample:
        base["load_amount"] = p.load_amount
        base["load_unit"] = p.load_unit
        base["predicted_amount"] = p.predicted_amount
        if p.residual is not None and has_load:
            base["residual_pct"] = round((p.residual / p.load_amount) * 100, 2)
    if with_recovery and p.predicted_amount is not None and has_load:
        base["known_amount"] = p.load_amount
        recovery = (p.predicted_amount / p.load_amount) * 100
        base["recovery_pct"] = round(recovery, 2)
        lo, hi = QC_RECOVERY_RANGE
        base["out_of_spec"] = not (lo <= recovery <= hi)
    if sample:
        base["estimated_amount"] = p.predicted_amount
    return base
