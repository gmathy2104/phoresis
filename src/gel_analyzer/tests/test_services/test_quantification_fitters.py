"""Tests for quantification fitters."""

import numpy as np
import pytest

from gel_analyzer.services.quantification import fitters


class TestLinear:
    def test_perfect_line(self):
        x = np.array([1, 2, 3, 4, 5], dtype=float)
        y = 2 * x + 1  # slope=2, intercept=1
        coeffs, r2, residuals = fitters.fit_linear(x, y)
        assert coeffs["a"] == pytest.approx(2.0)
        assert coeffs["b"] == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)
        assert all(abs(r) < 1e-9 for r in residuals)

    def test_inverse_predict(self):
        # given y = 2x + 1, inverse: x = (y - 1) / 2
        coeffs = {"a": 2.0, "b": 1.0}
        assert fitters.predict_linear_inverse(coeffs, 7.0) == pytest.approx(3.0)

    def test_inverse_returns_none_when_slope_zero(self):
        # a=0 means horizontal line — y can't determine x uniquely.
        coeffs = {"a": 0.0, "b": 1.0}
        assert fitters.predict_linear_inverse(coeffs, 5.0) is None

    def test_forward_predict(self):
        # Forward evaluation is what the service uses to project samples:
        # given x=area, y = a·area + b. With a=2, b=1, x=3 → y = 7.
        coeffs = {"a": 2.0, "b": 1.0}
        assert fitters.predict_linear(coeffs, 3.0) == pytest.approx(7.0)


class TestPoly2:
    def test_perfect_quadratic(self):
        x = np.array([0, 1, 2, 3, 4], dtype=float)
        y = 2 * x**2 + 3 * x + 1
        coeffs, r2, residuals = fitters.fit_poly2(x, y)
        assert r2 == pytest.approx(1.0)
        assert coeffs["coeffs"] == pytest.approx([2.0, 3.0, 1.0])

    def test_predict_inverse_returns_real_root_in_range(self):
        # y = 2x² + 3x + 1; pick x=2, y=15. Solve: 2x² + 3x + 1 - 15 = 0 → x = 2 or x ≈ -3.5
        # Service should return x=2 (positive root closest to interpolation range).
        coeffs = {"coeffs": [2.0, 3.0, 1.0]}
        x_range = (0.0, 4.0)
        assert fitters.predict_poly2_inverse(coeffs, 15.0, x_range=x_range) == pytest.approx(2.0)

    def test_predict_inverse_returns_none_when_no_real_root(self):
        # y = x² + 1 with target y=0: x² = -1 has no real solution.
        coeffs = {"coeffs": [1.0, 0.0, 1.0]}
        assert fitters.predict_poly2_inverse(coeffs, 0.0) is None


class TestFourPL:
    def test_4pl_converges_on_classic_dataset(self):
        # synthetic 4PL: a=0, d=100, c=10, b=1.2 → y = 100/(1+(x/10)^-1.2) more or less
        x = np.array([0.5, 1, 2, 5, 10, 20, 50, 100], dtype=float)
        a, d, c, b = 0.0, 100.0, 10.0, 1.2
        y = d + (a - d) / (1 + (x / c) ** b)
        coeffs, r2, residuals = fitters.fit_4pl(x, y)
        assert r2 > 0.999
        assert coeffs["c"] == pytest.approx(c, rel=0.05)

    def test_4pl_rejects_too_few_points(self):
        x = np.array([1, 2, 3], dtype=float)
        y = np.array([1, 2, 3], dtype=float)
        with pytest.raises(ValueError, match="at least 4"):
            fitters.fit_4pl(x, y)

    def test_4pl_inverse(self):
        coeffs = {"a": 0.0, "d": 100.0, "c": 10.0, "b": 1.2}
        # y = 50 → x = 10 (the c parameter, by definition)
        assert fitters.predict_4pl_inverse(coeffs, 50.0) == pytest.approx(10.0, rel=0.01)

    def test_4pl_inverse_returns_none_at_upper_asymptote(self):
        # y = d would require dividing by zero in the inverse formula.
        coeffs = {"a": 0.0, "d": 100.0, "c": 10.0, "b": 1.2}
        assert fitters.predict_4pl_inverse(coeffs, 100.0) is None
