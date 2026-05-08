"""Build the calibration-curve PNG for the report (Word + PowerPoint).

Mirrors the Pillow chart pattern in ``poi_purity_chart.py`` but uses the
matplotlib ``Agg`` backend so it can run inside the Celery worker without
a display. Returns raw PNG bytes ready to be wrapped in ``BytesIO`` and
embedded via python-docx ``add_picture`` or python-pptx ``add_picture``.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from phoresis_core.logging_config import get_logger  # noqa: E402

logger = get_logger(__name__)


def build_calibration_curve_png(
    *,
    points: list[tuple[float, float]],
    coeffs: dict,
    method: str,
    unit_label: str,
    controls: list[tuple[float, float]] | None = None,
    samples: list[tuple[float, float]] | None = None,
    width: int = 800,
    height: int = 600,
) -> bytes:
    """
    Render a calibration curve PNG.

    Args:
        points: Calibration points as (corrected_area, load_amount) tuples.
        coeffs: Fit coefficients matching ``method`` (LINEAR -> {a,b};
            POLYNOMIAL_2 -> {coeffs}; FOUR_PL -> {a,b,c,d}).
        method: One of "LINEAR", "POLYNOMIAL_2", "FOUR_PL".
        unit_label: Display unit on the y-axis (e.g. "ug" or "ug/mL").
        controls: Optional control points (corrected_area, predicted_amount).
        samples: Optional sample points (corrected_area, predicted_amount).
        width: PNG width in pixels.
        height: PNG height in pixels.

    Returns:
        Raw PNG bytes.
    """
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    ax.scatter(xs, ys, c="#8B5CF6", s=50, label="Calibration", zorder=3)

    if controls:
        ax.scatter(
            [c[0] for c in controls],
            [c[1] for c in controls],
            c="#06B6D4",
            marker="D",
            s=60,
            label="Controls",
            zorder=3,
        )
    if samples:
        ax.scatter(
            [s[0] for s in samples],
            [s[1] for s in samples],
            c="#9CA3AF",
            marker="x",
            s=40,
            label="Samples",
            zorder=2,
        )

    if xs:
        x_eval = np.linspace(min(xs), max(xs), 100)
        y_eval = None
        try:
            if method == "LINEAR":
                y_eval = coeffs["a"] * x_eval + coeffs["b"]
            elif method == "POLYNOMIAL_2":
                y_eval = np.polyval(coeffs["coeffs"], x_eval)
            elif method == "FOUR_PL":
                a = coeffs["a"]
                d = coeffs["d"]
                c = coeffs["c"]
                b = coeffs["b"]
                y_eval = d + (a - d) / (1 + (x_eval / c) ** b)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Calibration curve evaluation failed: {exc}")
            y_eval = None
        if y_eval is not None:
            ax.plot(x_eval, y_eval, c="#8B5CF6", linewidth=2, label="Fit", zorder=1)

    ax.set_xlabel("Corrected area")
    ax.set_ylabel(f"Amount ({unit_label})")
    ax.set_title("Protein quantification calibration")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()
