"""Curve-fitting primitives for protein quantification.

All fitters take 1-D numpy arrays (area, amount) and return:
  (coefficients_dict, r_squared, residuals)

Inverse predictors take coefficients + observed area and return predicted amount.
The inverse for poly2 picks the root closest to the original interpolation range
to stay physically meaningful (load amount > 0)."""

from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

from gel_analyzer.services.calibration.fitters_shared import fit_polynomial, format_polynomial_equation

# ---------- Linear y = a·x + b ----------------------------------------------


def fit_linear(area: np.ndarray, amount: np.ndarray):
    """Fit y = a·x + b. Returns ({a, b}, r², residuals)."""
    coeffs_list, r2, residuals = fit_polynomial(area, amount, 1)
    a, b = float(coeffs_list[0]), float(coeffs_list[1])
    return {"a": a, "b": b}, r2, residuals


def predict_linear(coeffs: dict, area: float) -> float:
    """Forward evaluation: given x = area, return y = a·area + b.

    Used by the projection path (sample area → predicted amount). The
    inverse direction lives in `predict_linear_inverse`.
    """
    return coeffs["a"] * area + coeffs["b"]


def predict_linear_inverse(coeffs: dict, amount: float) -> float | None:
    """Given y = a·x + b and observed y, return x = (y - b) / a, or None if a=0."""
    a, b = coeffs.get("a", 0.0), coeffs.get("b", 0.0)
    if a == 0:
        return None
    return (amount - b) / a


def linear_equation(coeffs: dict, unit: str) -> str:
    a, b = coeffs["a"], coeffs["b"]
    sign = "+" if b >= 0 else "-"
    return f"{unit} = {a:.4g}·area {sign} {abs(b):.4g}"


# ---------- Polynomial deg 2 y = a·x² + b·x + c -----------------------------


def fit_poly2(area: np.ndarray, amount: np.ndarray):
    coeffs_list, r2, residuals = fit_polynomial(area, amount, 2)
    return {"coeffs": [float(c) for c in coeffs_list]}, r2, residuals


def predict_poly2_inverse(coeffs: dict, amount: float, x_range: tuple[float, float] | None = None) -> float | None:
    """Solve a·x² + b·x + c - amount = 0. Pick the root closest to x_range mid (or the
    positive one if x_range is None). Return None if no real root."""
    a, b, c = coeffs["coeffs"]
    discriminant = b * b - 4 * a * (c - amount)
    if discriminant < 0:
        return None
    sqrt_d = np.sqrt(discriminant)
    if a == 0:
        # degenerate: linear case
        return None if b == 0 else (amount - c) / b
    r1 = (-b + sqrt_d) / (2 * a)
    r2 = (-b - sqrt_d) / (2 * a)
    if x_range is not None:
        target = (x_range[0] + x_range[1]) / 2
        return r1 if abs(r1 - target) <= abs(r2 - target) else r2
    return r1 if r1 >= 0 else r2


def poly2_equation(coeffs: dict, unit: str) -> str:
    return format_polynomial_equation(coeffs["coeffs"], var="area", lhs=unit)


# ---------- 4-Parameter Logistic --------------------------------------------


def _four_pl(x, a, d, c, b):
    """4PL function: y = d + (a - d) / (1 + (x / c) ** b)."""
    return d + (a - d) / (1 + (x / c) ** b)


def fit_4pl(area: np.ndarray, amount: np.ndarray):
    """Fit y = d + (a - d) / (1 + (x / c)^b). Requires >= 4 points."""
    if len(area) < 4:
        raise ValueError("4PL requires at least 4 points")
    a0 = float(np.min(amount))
    d0 = float(np.max(amount))
    c0 = float(np.median(area))
    b0 = 1.0
    try:
        popt, _ = curve_fit(
            _four_pl,
            area,
            amount,
            p0=[a0, d0, c0, b0],
            maxfev=5000,
        )
    except Exception as e:
        raise ValueError(f"4PL did not converge: {e}") from e
    a, d, c, b = (float(v) for v in popt)
    predicted = _four_pl(area, a, d, c, b)
    ss_res = np.sum((amount - predicted) ** 2)
    ss_tot = np.sum((amount - np.mean(amount)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    residuals = amount - predicted
    return {"a": a, "d": d, "c": c, "b": b}, float(r2), residuals


def predict_4pl_inverse(coeffs: dict, amount: float) -> float | None:
    """Solve 4PL for x given y. y = d + (a-d)/(1 + (x/c)^b) → x = c * ((a-d)/(y-d) - 1)^(1/b)."""
    a, d, c, b = coeffs["a"], coeffs["d"], coeffs["c"], coeffs["b"]
    try:
        ratio = (a - d) / (amount - d)
        if ratio <= 1:
            return None
        return c * (ratio - 1) ** (1.0 / b)
    except (ZeroDivisionError, ValueError):
        return None


def four_pl_equation(coeffs: dict, unit: str) -> str:
    a, d, c, b = coeffs["a"], coeffs["d"], coeffs["c"], coeffs["b"]
    return f"{unit} = {d:.4g} + ({a:.4g} - {d:.4g}) / (1 + (area / {c:.4g})^{b:.4g})"
