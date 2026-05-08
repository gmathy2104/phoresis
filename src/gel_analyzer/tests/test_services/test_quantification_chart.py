"""Tests for the calibration-curve PNG renderer."""

from io import BytesIO

from PIL import Image

from gel_analyzer.services.report.quantification_chart import build_calibration_curve_png


def test_returns_png_bytes_linear():
    points = [(1000, 5), (2000, 10), (3000, 15)]
    coeffs = {"a": 0.005, "b": 0}
    blob = build_calibration_curve_png(
        points=points,
        coeffs=coeffs,
        method="LINEAR",
        unit_label="ug",
        controls=[(1500, 7.5)],
        samples=[(2500, 12.5)],
    )
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    img = Image.open(BytesIO(blob))
    assert img.format == "PNG"
    assert img.size[0] > 0 and img.size[1] > 0


def test_polynomial_2_renders():
    points = [(1000, 5), (2000, 10), (3000, 15), (4000, 25)]
    coeffs = {"coeffs": [1e-6, 0.004, 0.5]}
    blob = build_calibration_curve_png(
        points=points,
        coeffs=coeffs,
        method="POLYNOMIAL_2",
        unit_label="ug",
    )
    img = Image.open(BytesIO(blob))
    assert img.format == "PNG"


def test_four_pl_renders():
    points = [(100, 1), (1000, 5), (5000, 12), (10000, 18), (20000, 22)]
    coeffs = {"a": 25.0, "d": 0.0, "c": 5000.0, "b": 1.2}
    blob = build_calibration_curve_png(
        points=points,
        coeffs=coeffs,
        method="FOUR_PL",
        unit_label="ug/mL",
    )
    img = Image.open(BytesIO(blob))
    assert img.format == "PNG"


def test_handles_no_controls_no_samples():
    points = [(1000, 5), (2000, 10)]
    coeffs = {"a": 0.005, "b": 0}
    blob = build_calibration_curve_png(
        points=points,
        coeffs=coeffs,
        method="LINEAR",
        unit_label="ug",
    )
    img = Image.open(BytesIO(blob))
    assert img.format == "PNG"
