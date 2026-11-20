"""Tests for the unified noise estimator used by all band detectors."""

import numpy as np

from gel_analyzer.services.band_detection.profile_processor import NoiseProfile, estimate_noise_profile


class TestNoiseProfileDataclass:
    """Dataclass shape and defaults."""

    def test_dataclass_has_expected_fields(self):
        np_ = NoiseProfile(
            noise_signal=1.0,
            noise_d1=0.1,
            noise_d2=0.01,
            baseline_count=100,
            baseline_percentile=25.0,
            fallback_reason=None,
        )
        assert np_.noise_signal == 1.0
        assert np_.baseline_percentile == 25.0
        assert np_.fallback_reason is None


class TestEstimateNoiseProfileAdaptive:
    """estimate_noise_profile() adapts its baseline percentile based on profile skew."""

    def test_sparse_profile_uses_50_percentile(self):
        """A profile with 1 tall peak in mostly-flat background (positive skew
        relative to our threshold) picks the 50% baseline cutoff."""
        rng = np.random.default_rng(42)
        n = 400
        noise = rng.normal(0, 1.0, size=n)
        peak = np.zeros(n)
        peak[200:220] = 50.0  # one tall narrow peak
        data = noise + peak

        profile = estimate_noise_profile(data)

        assert profile.baseline_percentile == 50.0
        assert profile.fallback_reason is None
        assert 0.5 < profile.noise_signal < 2.0  # should recover ~1.0

    def test_dense_profile_uses_25_percentile(self):
        """A profile with many peaks (band-dense, post-polarity-correction)
        picks the 25% cutoff because the skew is low positive (distribution
        is near-bimodal, so the 50th percentile is still inside bands)."""
        rng = np.random.default_rng(42)
        n = 400
        noise = rng.normal(0, 1.0, size=n)
        peaks = np.zeros(n)
        for center in range(30, 400, 40):  # 10 peaks evenly spaced
            peaks[center : center + 15] = 40.0
        data = noise + peaks

        profile = estimate_noise_profile(data)

        assert profile.baseline_percentile == 25.0
        assert profile.fallback_reason is None

    def test_flat_signal_falls_back(self):
        """A signal where max-min < 5 triggers the flat-signal fallback."""
        data = np.full(300, 100.0) + np.random.default_rng(0).normal(0, 0.1, 300)

        profile = estimate_noise_profile(data)

        assert profile.fallback_reason == "flat_signal"
        assert profile.noise_signal > 0  # some noise detected

    def test_too_short_falls_back(self):
        """Profile with < 80 samples can't produce 20 baseline points at 25%."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0] * 10)  # 50 samples

        profile = estimate_noise_profile(data)

        assert profile.fallback_reason == "too_few_baseline"

    def test_includes_derivative_noise_when_provided(self):
        """Passing d1/d2 returns their MAD in the corresponding fields."""
        rng = np.random.default_rng(0)
        data = rng.normal(0, 1.0, size=400)
        d1 = np.gradient(data)
        d2 = np.gradient(d1)

        profile = estimate_noise_profile(data, d1=d1, d2=d2)

        assert profile.noise_d1 > 0
        assert profile.noise_d2 > 0

    def test_no_derivatives_returns_zero_d1_d2(self):
        """Without d1/d2, those fields are 0.0."""
        data = np.random.default_rng(0).normal(0, 1.0, size=400)

        profile = estimate_noise_profile(data)

        assert profile.noise_d1 == 0.0
        assert profile.noise_d2 == 0.0

    def test_noise_floor_applied(self):
        """Pure constant data returns noise >= 1e-10, never zero."""
        data = np.full(300, 100.0)
        d1 = np.zeros(300)
        d2 = np.zeros(300)

        profile = estimate_noise_profile(data, d1=d1, d2=d2)

        assert profile.noise_signal >= 1e-10
        assert profile.noise_d1 >= 1e-10
        assert profile.noise_d2 >= 1e-10


class TestBandDetectionParamsNewFields:
    """New params added in phase 1 noise cleanup."""

    def test_valley_d2_factor_default_is_1_5(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        params = BandDetectionParams()
        assert params.valley_d2_factor == 1.5

    def test_valley_d2_factor_clamped_low(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        params = BandDetectionParams(valley_d2_factor=0.1)
        assert params.valley_d2_factor == 0.5

    def test_valley_d2_factor_clamped_high(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        params = BandDetectionParams(valley_d2_factor=20.0)
        assert params.valley_d2_factor == 5.0

    def test_to_dict_includes_new_field(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        d = BandDetectionParams(valley_d2_factor=2.0).to_dict()
        assert d["valley_d2_factor"] == 2.0

    def test_from_dict_accepts_new_field(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        params = BandDetectionParams.from_dict({"valley_d2_factor": 3.0})
        assert params.valley_d2_factor == 3.0

    def test_scaled_preserves_relative_factor(self):
        """valley_d2_factor is a relative multiplier, not scaled by image height."""
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        base = BandDetectionParams(valley_d2_factor=2.5)
        scaled = base.scaled(image_height=1638)  # 2× reference
        assert scaled.valley_d2_factor == 2.5


class TestMinBandWidthDefault:
    """min_band_width_px default raised from 3 to 5 to exclude speckle-scale features."""

    def test_default_is_5_px(self):
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        assert BandDetectionParams().min_band_width_px == 5

    def test_user_can_still_set_lower(self):
        """The raise is a default, not a floor — high-res users can override."""
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        p = BandDetectionParams(min_band_width_px=2)
        assert p.min_band_width_px == 2


class TestRollingBallGuardrail:
    """Warning log when rolling_ball_radius is smaller than max_band_width_px.

    The project uses loguru; stdlib caplog doesn't capture loguru output,
    so we monkeypatch logger.warning directly to inspect the call.
    """

    def _build_profile(self, n=400):
        from gel_analyzer.services.band_detection.models import IntensityProfile

        raw = list(np.random.default_rng(0).normal(100, 5, size=n))
        return IntensityProfile(
            y_positions=list(range(n)),
            raw_intensities=raw,
            lane_height=n,
        )

    def test_warns_when_radius_below_max_band_width(self, monkeypatch):
        from gel_analyzer.services.band_detection import profile_processor as pp_mod
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        warnings_captured: list[str] = []
        monkeypatch.setattr(
            pp_mod.logger,
            "warning",
            lambda msg, *a, **kw: warnings_captured.append(str(msg)),
        )

        params = BandDetectionParams(rolling_ball_radius=20, max_band_width_px=100)
        pp_mod.ProfileProcessor(params).process(self._build_profile())

        assert any("rolling_ball_radius=20" in m and "max_band_width_px=100" in m for m in warnings_captured), (
            f"Expected guardrail warning not found; got: {warnings_captured}"
        )

    def test_does_not_warn_when_radius_sufficient(self, monkeypatch):
        from gel_analyzer.services.band_detection import profile_processor as pp_mod
        from gel_analyzer.services.band_detection.models import BandDetectionParams

        warnings_captured: list[str] = []
        monkeypatch.setattr(
            pp_mod.logger,
            "warning",
            lambda msg, *a, **kw: warnings_captured.append(str(msg)),
        )

        params = BandDetectionParams(rolling_ball_radius=150, max_band_width_px=100)
        pp_mod.ProfileProcessor(params).process(self._build_profile())

        for msg in warnings_captured:
            assert not ("rolling_ball_radius=150" in msg and "< max_band_width_px" in msg), (
                f"Did not expect guardrail warning when radius >= max_band_width; got: {msg}"
            )
