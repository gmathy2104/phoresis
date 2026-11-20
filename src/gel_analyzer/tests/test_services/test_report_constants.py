# gel_analyzer/tests/test_services/test_report_constants.py
"""Ph0: single-source palette + font + matplotlib-style helpers."""

from unittest import mock

from PIL import ImageFont

from gel_analyzer.models import Band, Lane
from gel_analyzer.services.report import constants as C


def test_calibration_present_in_every_palette():
    assert "CALIBRATION" in C.LANE_PALETTE
    assert "CALIBRATION" in C.LANE_PALETTE_HEX
    assert "CALIBRATION" in C.BAND_PALETTE
    assert "CALIBRATION" in C.BAND_PALETTE_HEX


def test_calibration_hex_is_red_400():
    assert C.LANE_PALETTE_HEX["CALIBRATION"] == "#F87171"
    assert C.BAND_PALETTE_HEX["CALIBRATION"] == "#F87171"


def test_calibration_rgba_matches_f87171():
    # #F87171 -> (248, 113, 113)
    assert C.LANE_PALETTE["CALIBRATION"]["stroke"][:3] == (248, 113, 113)
    assert C.BAND_PALETTE["CALIBRATION"]["stroke"][:3] == (248, 113, 113)
    assert C.LANE_PALETTE["CALIBRATION"]["dashed"] is False


def test_every_lane_enum_code_resolves_to_a_palette():
    for code, _label in Lane.LaneType.choices:
        assert code in C.LANE_PALETTE, f"LANE_PALETTE missing {code}"
        assert code in C.LANE_PALETTE_HEX, f"LANE_PALETTE_HEX missing {code}"


def test_every_band_enum_code_resolves_to_a_palette():
    for code, _label in Band.BandType.choices:
        assert code in C.BAND_PALETTE, f"BAND_PALETTE missing {code}"
        assert code in C.BAND_PALETTE_HEX, f"BAND_PALETTE_HEX missing {code}"


def test_lane_and_band_colors_helpers_resolve_calibration():
    assert C.lane_colors("CALIBRATION")["stroke"][:3] == (248, 113, 113)
    assert C.band_colors("CALIBRATION")["stroke"][:3] == (248, 113, 113)


def test_calibration_display_names_present():
    assert C.LANE_TYPE_DISPLAY["CALIBRATION"]
    assert C.BAND_TYPE_DISPLAY["CALIBRATION"]


def test_resolve_pil_font_returns_a_font_at_requested_size():
    font = C.resolve_pil_font(18)
    assert font is not None
    assert hasattr(font, "getbbox") or hasattr(font, "getsize")


def test_resolve_pil_font_prefers_truetype_when_available():
    # When truetype succeeds for the first matching candidate, resolve_pil_font
    # must return that font object — not the bitmap load_default().
    fake_font = mock.MagicMock()
    fake_font.getbbox = lambda text: (0, 0, 10, 14)

    def fake_truetype(name, size=12, **kwargs):
        # Succeed on any candidate — simulates a font being available
        return fake_font

    with (
        mock.patch.object(ImageFont, "truetype", side_effect=fake_truetype),
        mock.patch.object(ImageFont, "load_default") as mock_default,
    ):
        font = C.resolve_pil_font(14)
    assert font is fake_font
    mock_default.assert_not_called()


def test_resolve_pil_font_falls_back_to_default_and_warns_once():
    C._FONT_FALLBACK_WARNED = False  # reset the warn-once latch
    sentinel = mock.MagicMock(name="bitmap_default")
    with (
        mock.patch.object(ImageFont, "truetype", side_effect=OSError("no fonts")),
        mock.patch.object(ImageFont, "load_default", return_value=sentinel),
        mock.patch.object(C.logger, "warning") as warn,
    ):
        f1 = C.resolve_pil_font(12)
        f2 = C.resolve_pil_font(20)
    assert f1 is sentinel
    assert f2 is sentinel
    # warn-once: exactly one fallback warning across the two calls
    assert warn.call_count == 1


def test_render_gel_overlay_uses_resolve_pil_font():
    """render_gel_overlay must call resolve_pil_font at least once when drawing text.

    Ph1 Task1 removed _font_pair and calls resolve_pil_font directly; this test
    verifies the delegation contract at the new call site.
    """
    import io
    from types import SimpleNamespace

    import numpy as np
    from PIL import Image

    from gel_analyzer.services.report import gel_overlay
    from gel_analyzer.services.report.gel_overlay import GelOverlayVariant, render_gel_overlay

    # Build a minimal in-memory white PNG (1 SAMPLE lane, no bands).
    arr = np.full((200, 200), 220, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    lane = SimpleNamespace(
        lane_type_code="SAMPLE",
        lane_type="Sample Lane",
        lane_number=1,
        sample_name="S1",
        x=20,
        y=10,
        width=40,
        height=180,
        polygon=None,
        bands=[],
    )

    calls = []
    real = C.resolve_pil_font

    def spy(size):
        calls.append(size)
        return real(size)

    with mock.patch.object(gel_overlay, "resolve_pil_font", side_effect=spy):
        result = render_gel_overlay(buf, [lane], variant=GelOverlayVariant.LANES_ONLY)

    assert result is not None, "render_gel_overlay must return a PNG buffer"
    # LANES_ONLY draws lane number + optional sample label — both use resolved fonts.
    assert len(calls) >= 1, "resolve_pil_font must be called at least once for text labels"


def test_mpl_style_enforces_high_dpi_and_no_tight_bbox():
    style = C.mpl_style()
    assert isinstance(style, dict)
    assert style["figure.dpi"] >= 200
    assert style["savefig.dpi"] >= 200
    # No tight bbox: deterministic pixel size (rely on aspect-locked placement)
    assert style["savefig.bbox"] == "standard"


def test_mpl_style_is_applicable_in_rc_context():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style = C.mpl_style()
    with plt.rc_context(style):
        assert plt.rcParams["figure.dpi"] >= 200
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        plt.close(fig)


def test_mpl_style_does_not_mutate_global_rcparams():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    before = plt.rcParams["figure.dpi"]
    _ = C.mpl_style()
    assert plt.rcParams["figure.dpi"] == before


def test_densitometry_electropherogram_peak_colors_are_current():
    """The PEAK_COLORS dict embedded in _render_electropherogram must
    match the gold-standard palette: POI purple, MW orange, OTHER green.

    Step 3 writes the *variable reference* (BAND_PALETTE_HEX['POI']) into
    the source, NOT the literal hex — so asserting "#A855F7" in src would
    fail permanently. We therefore assert the resolved constants directly
    and keep only a negative source guard that the stale amber is gone."""
    import inspect

    from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder

    # Resolved constants are the real contract (POI purple, MW orange).
    assert C.BAND_PALETTE_HEX["POI"] == "#A855F7"
    assert C.BAND_PALETTE_HEX["MW_REFERENCE"] == "#F97316"

    # Negative source guard only: the stale amber must be gone.
    src = inspect.getsource(DensitometryReportBuilder._render_electropherogram)
    assert "#FFC107" not in src, "MW peak color still amber #FFC107"
