"""Electropherogram peak-color contract (Ph1, spec §5)."""

from gel_analyzer.services.report.constants import BAND_PALETTE_HEX


def test_band_palette_hex_has_corrected_values():
    assert BAND_PALETTE_HEX["POI"] == "#A855F7"
    assert BAND_PALETTE_HEX["MW_REFERENCE"] == "#F97316"
    # Spec §5: OTHER electropherogram markers are green (annotation-view parity),
    # NOT the old #9E9E9E grey.
    assert BAND_PALETTE_HEX["OTHER"] == "#22C55E"


def test_densito_electropherogram_uses_corrected_peak_colors():
    """Render an electropherogram and assert POI is no longer green, and that an
    OTHER band IS now green (#22C55E), per spec §5."""
    from types import SimpleNamespace

    import numpy as np
    from PIL import Image

    from gel_analyzer.services.report.densitometry_builder import DensitometryReportBuilder

    poi = SimpleNamespace(band_type="Protein of Interest", estimated_mw_kda=50.0, position_y=200)
    lane = SimpleNamespace(
        sample_name="S1",
        lane_number=1,
        bands=[poi],
        profile_data={
            "intensities": list(np.linspace(0, 100, 50)),
            "y_positions": list(range(50)),
            "mw_values": list(np.linspace(150, 10, 50)),
        },
    )
    b = DensitometryReportBuilder.__new__(DensitometryReportBuilder)
    buf = b._render_electropherogram(lane, index=0)
    assert buf is not None
    img = Image.open(buf).convert("RGB")
    px = np.asarray(img)
    # POI is now purple #A855F7 ≈ (168,85,247) — it must NOT be the old green #22C55E (34,197,94).
    poi_green = (
        (np.abs(px[:, :, 0].astype(int) - 34) < 10)
        & (np.abs(px[:, :, 1].astype(int) - 197) < 10)
        & (np.abs(px[:, :, 2].astype(int) - 94) < 10)
    )
    assert not poi_green.any(), "POI marker must no longer be #22C55E green"

    # Now an OTHER band must render GREEN (#22C55E), not the old grey #9E9E9E (158,158,158).
    other = SimpleNamespace(band_type="Other", estimated_mw_kda=30.0, position_y=300)
    other_lane = SimpleNamespace(
        sample_name="S2",
        lane_number=2,
        bands=[other],
        profile_data={
            "intensities": list(np.linspace(0, 100, 50)),
            "y_positions": list(range(50)),
            "mw_values": list(np.linspace(150, 10, 50)),
        },
    )
    obuf = b._render_electropherogram(other_lane, index=1)
    assert obuf is not None
    opx = np.asarray(Image.open(obuf).convert("RGB"))
    other_green = (
        (np.abs(opx[:, :, 0].astype(int) - 34) < 12)
        & (np.abs(opx[:, :, 1].astype(int) - 197) < 12)
        & (np.abs(opx[:, :, 2].astype(int) - 94) < 12)
    )
    assert other_green.any(), "OTHER marker must now be green #22C55E (spec §5), not grey"
