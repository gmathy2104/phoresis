"""Unit tests for the consolidated digital-gel renderer (Ph1)."""

import io
from types import SimpleNamespace

import numpy as np
from PIL import Image

from gel_analyzer.services.report.digital_gel import render_digital_gel


def _band(*, code="OTHER", mw=None, y=100, pct=20.0):
    return SimpleNamespace(
        band_type_code=code,
        band_type={
            "POI": "Protein of Interest",
            "OTHER": "Other",
            "MW_REFERENCE": "MW Reference",
            "CALIBRATION": "Calibration Point",
        }[code],
        estimated_mw_kda=mw,
        position_y=y,
        relative_percent_lane=pct,
    )


def _lane(*, code="SAMPLE", number=1, bands=None, h=480, sample="S", gel_type="SDS-PAGE"):
    return SimpleNamespace(
        lane_type_code=code,
        lane_type={
            "SAMPLE": "Sample",
            "LADDER": "MW Ladder",
            "CONTROL": "Control",
            "EMPTY": "Empty",
            "CALIBRATION": "Calibration",
            "DOT": "Dot",
        }[code],
        lane_number=number,
        sample_name=sample,
        height=h,
        gel_type=gel_type,
        bands=bands or [],
    )


def _open(buf):
    return Image.open(buf).convert("RGB")


def test_returns_buffer_for_calibrated_lanes():
    lanes = [_lane(bands=[_band(mw=75, y=100), _band(mw=25, y=300)])]
    buf = render_digital_gel(lanes, calibration=None)
    assert buf is not None
    img = _open(buf)
    assert img.width > 0 and img.height > 0


def test_fully_uncalibrated_gel_renders_without_a_made_up_kda_ruler():
    """Bug: the PPTX builder returned None when no band had an MW.

    Bug: the MW column then drew a 10-250 kDa ruler, grid lines across every lane, beside
    bands placed on their own lane's position_y range: a band read as an MW the lab never
    estimated."""
    from gel_analyzer.services.report import digital_gel as dg

    def scale_column(lanes):
        buf = render_digital_gel(lanes, calibration=None)
        assert buf is not None, "uncalibrated gels must still render"
        img = np.asarray(_open(buf), dtype=int)
        # The rightmost MW column, body rows below its "No MW calibration" label.
        return img[dg._HEADER_HEIGHT + 40 : dg._HEADER_HEIGHT + dg._BODY_HEIGHT, -dg._MW_SCALE_WIDTH :]

    calibrated = [_lane(bands=[_band(mw=75, y=100), _band(mw=25, y=300)])]
    uncalibrated = [_lane(bands=[_band(mw=None, y=100), _band(mw=None, y=300)])]
    assert (scale_column(calibrated) != dg._BG_COLOR).any(), "control: a calibrated gel draws its ruler here"
    assert (scale_column(uncalibrated) == dg._BG_COLOR).all(), "no-MW gel drew a kDa ruler the lab never estimated"


def test_empty_lane_list_returns_none():
    assert render_digital_gel([], calibration=None) is None


def test_exclude_codes_filters_empty_lanes():
    """An EMPTY lane is excluded by default; a single EMPTY lane → None."""
    lanes = [_lane(code="EMPTY", bands=[])]
    assert render_digital_gel(lanes, calibration=None) is None


def test_calibrated_placement_high_mw_at_top():
    """In a calibrated lane, the higher-MW band must sit above the lower-MW band."""
    from gel_analyzer.services.report import digital_gel as dg

    lanes = [_lane(bands=[_band(mw=150, y=80), _band(mw=15, y=400)])]
    # Use the module's placement helper directly for a deterministic assertion.
    mw_min, mw_max = dg._global_mw_range(lanes)
    y_hi = dg._calibrated_y(150, mw_min, mw_max, body_top=0, body_h=400)
    y_lo = dg._calibrated_y(15, mw_min, mw_max, body_top=0, body_h=400)
    assert y_hi < y_lo, "150 kDa must render above 15 kDa (smaller Y = higher)"


def test_center_fallback_when_no_mw_no_position():
    from gel_analyzer.services.report import digital_gel as dg

    # Degenerate lane: single band, no MW, equal min==max → centered.
    bands = [_band(mw=None, y=200)]
    lane = _lane(bands=bands)
    lane_min, lane_max = dg._positions_range([lane])
    y = dg._uncalibrated_y(200, lane_min, lane_max, body_top=0, body_h=400)
    assert y == 200, "degenerate (min==max) lane must center the band"


def test_mixed_calibrated_and_uncalibrated_lanes():
    """A calibrated lane and an uncalibrated lane in the same image; no crash."""
    calibrated = _lane(number=1, bands=[_band(mw=75, y=100), _band(mw=25, y=300)])
    uncalibrated = _lane(number=2, bands=[_band(mw=None, y=120), _band(mw=None, y=280)])
    buf = render_digital_gel([calibrated, uncalibrated], calibration=None)
    assert buf is not None
    assert _open(buf).width > 0


def test_footer_field_is_read_dynamically():
    """footer_field='gel_type' must not raise (comparison path)."""
    lanes = [_lane(bands=[_band(mw=50, y=200)], gel_type="Native-PAGE")]
    buf = render_digital_gel(lanes, calibration=None, footer_field="gel_type")
    assert buf is not None


def test_densito_builder_delegates_to_render_digital_gel(monkeypatch):
    from gel_analyzer.services.report import densitometry_builder as d_mod

    captured = {}

    def fake(lanes, *, calibration, footer_field="lane_type", exclude_codes=("EMPTY",), color_key="code"):
        captured["footer_field"] = footer_field
        return io.BytesIO(b"x")

    monkeypatch.setattr(d_mod, "render_digital_gel", fake, raising=False)
    b = d_mod.DensitometryReportBuilder.__new__(d_mod.DensitometryReportBuilder)
    out = b._render_digital_gel([_lane(bands=[_band(mw=50)])])
    assert out is not None
    assert captured["footer_field"] == "lane_type"


def test_comparison_builder_delegates_with_gel_type_footer(monkeypatch):
    from gel_analyzer.services.report import comparison_builder as c_mod

    captured = {}

    def fake(lanes, *, calibration, footer_field="lane_type", exclude_codes=("EMPTY",), color_key="code"):
        captured["footer_field"] = footer_field
        return io.BytesIO(b"x")

    monkeypatch.setattr(c_mod, "render_digital_gel", fake, raising=False)
    b = c_mod.ComparisonReportBuilder.__new__(c_mod.ComparisonReportBuilder)
    out = b._render_digital_gel([_lane(bands=[_band(mw=50)])])
    assert out is not None
    assert captured["footer_field"] == "gel_type"


def test_densito_pptx_delegates(monkeypatch):
    from gel_analyzer.services.report import densitometry_pptx_builder as p_mod

    captured = {}

    def fake(lanes, *, calibration, footer_field="lane_type", exclude_codes=("EMPTY",), color_key="code"):
        captured["called"] = True
        captured["footer_field"] = footer_field
        return io.BytesIO(b"x")

    monkeypatch.setattr(p_mod, "render_digital_gel", fake, raising=False)
    b = p_mod.DensitometryPowerPointBuilder.__new__(p_mod.DensitometryPowerPointBuilder)
    # Even a fully-uncalibrated lane must produce a buffer (old code returned None).
    out = b._render_digital_gel([_lane(bands=[_band(mw=None, y=100)])])
    assert out is not None
    assert captured.get("called") is True
    assert captured["footer_field"] == "lane_type"


def test_comparison_pptx_has_no_new_hack():
    """The brittle ComparisonReportBuilder.__new__ reuse must be gone FROM
    _add_digital_gel_slide, and that method must now delegate to render_digital_gel.

    NOTE: the whole-file string 'ComparisonReportBuilder.__new__' appears at
    ~5 sites in this module (e.g. ~360, 406, 487, 524, 549); Ph1 only replaces
    the one inside _add_digital_gel_slide, so the assertion MUST be scoped to
    that method via inspect.getsource — a whole-file assertion would fail after
    a correct implementation.
    """
    import inspect

    from gel_analyzer.services.report.comparison_pptx_builder import ComparisonPowerPointBuilder

    method_src = inspect.getsource(ComparisonPowerPointBuilder._add_digital_gel_slide)
    assert "ComparisonReportBuilder.__new__" not in method_src, (
        "_add_digital_gel_slide must no longer reuse ComparisonReportBuilder via __new__"
    )
    assert "render_digital_gel(" in method_src, "_add_digital_gel_slide must now delegate to render_digital_gel"
    # Allow both quote styles (black normalises single → double quotes).
    assert "footer_field='gel_type'" in method_src or 'footer_field="gel_type"' in method_src, (
        "the comparison PPTX delegation must pass footer_field='gel_type'"
    )
    assert "exclude_codes=()" in method_src, (
        "_add_digital_gel_slide must pass exclude_codes=() to preserve EMPTY lanes in comparison PPTX"
    )


def _poi_rows(img, column):
    """The image rows where lane ``column`` (0-based, left to right) shows its POI band's purple, below the header."""
    from gel_analyzer.services.report import digital_gel as dg

    x = dg._LANE_GAP + column * (dg._LANE_WIDTH + dg._LANE_GAP) + dg._LANE_WIDTH // 2
    pixels = np.asarray(img)
    return [
        y
        for y in range(dg._HEADER_HEIGHT + dg._ACCENT_BAR_HEIGHT, dg._HEADER_HEIGHT + dg._BODY_HEIGHT)
        if pixels[y, x, 2] > 140 and pixels[y, x, 1] < 110 and pixels[y, x, 0] > 90
    ]


def test_bands_level_on_the_gel_are_level_on_the_digital_gel_when_the_samples_have_no_mw():
    """A ladder with MW, two sample lanes without: their POI bands, at the same row of the gel, were stretched over
    each lane's own band range against the ladder's kDa grid -- one at the bottom of its lane, one at the top (found
    2026-10-13: one gel's POI bands read 9 to 110 kDa). Every band now sits at its position on the gel."""
    ladder = _lane(
        code="LADDER", number=1, bands=[_band(code="MW_REFERENCE", mw=mw, y=y) for mw, y in ((250, 50), (10, 350))]
    )
    lane_a = _lane(number=2, bands=[_band(mw=None, y=100), _band(code="POI", mw=None, y=200)])
    lane_b = _lane(number=3, bands=[_band(code="POI", mw=None, y=200), _band(mw=None, y=300)])
    img = _open(render_digital_gel([ladder, lane_a, lane_b], calibration=None))
    rows_a, rows_b = _poi_rows(img, 1), _poi_rows(img, 2)
    assert rows_a and rows_b
    assert abs(sum(rows_a) / len(rows_a) - sum(rows_b) / len(rows_b)) <= 1
