"""Curve-fit helpers shared between MW calibration (gel_analyzer.services.calibration)
and protein quantification calibration (gel_analyzer.services.quantification).

Behaviour-preserving extraction from CalibrationService — function bodies are copied
verbatim from service.py, only the residual write-back is parameterized via a
callback so quantification's BandMatch can be a different shape."""

from __future__ import annotations

import numpy as np
from scipy.stats import linregress


def fit_log_linear(
    rf: np.ndarray, log_mw: np.ndarray
) -> tuple[float, float, float, np.ndarray]:
    """log10(MW) = slope·Rf + intercept. Returns (slope, intercept, r_squared, residuals)."""
    result = linregress(rf, log_mw)
    predicted = result.slope * rf + result.intercept
    residuals = log_mw - predicted
    return float(result.slope), float(result.intercept), float(result.rvalue ** 2), residuals


def fit_polynomial(
    x: np.ndarray, y: np.ndarray, degree: int
) -> tuple[list[float], float, np.ndarray]:
    """Generic polynomial fit. Returns (coeffs, r_squared, residuals)."""
    coeffs = np.polyfit(x, y, degree)
    predicted = np.polyval(coeffs, x)
    ss_res = np.sum((y - predicted) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    residuals = y - predicted
    return coeffs.tolist(), float(r_squared), residuals


def format_polynomial_equation(coeffs: list[float], var: str = "x", lhs: str = "y") -> str:
    """Format polynomial coefficients as a human-readable equation string."""
    terms: list[str] = []
    degree = len(coeffs) - 1
    for i, c in enumerate(coeffs):
        power = degree - i
        c_str = f"{c:.4f}"
        if power == 0:
            terms.append(c_str)
        elif power == 1:
            terms.append(f"{c_str}*{var}")
        else:
            terms.append(f"{c_str}*{var}^{power}")
    return f"{lhs} = " + " + ".join(terms)
