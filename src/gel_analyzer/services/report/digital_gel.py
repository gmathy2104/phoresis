"""
Consolidated synthetic "digital gel" renderer for reports.

Replaces the three near-identical `_render_digital_gel` methods that lived in
comparison_builder, densitometry_builder and densitometry_pptx_builder. Used by
Word AND PowerPoint, comparison AND densitometry.

Placement:
  1. every drawn band carries an MW (estimated_mw_kda) → one log10 kDa axis, HIGH MW at top;
  2. else every band sits at its position on its gel (position_y), on ONE scale per gel -- the drawn lanes' band
     range -- so a band level with another on the gel is level here. Its kDa labels are the gel's ladder bands
     (their MW at their position), with one gel only: lanes of two gels share no scale;
  3. neither MW nor position → centered (last resort).
Until 2026-10-13 a lane without MW was stretched over its OWN band range and drawn against the kDa grid of the
ladder's calibrated bands: the POI bands of one gel, all level on the gel, read 9 to 110 kDa.
Lanes without MW keep an amber header dot. We never drop MW-less bands and never return None
just because a gel is uncalibrated; with no ladder band to label, the scale column says "No MW calibration".
"""

import math
from io import BytesIO

from .constants import band_colors

# Amber "uncalibrated" indicator (front-end #F59E0B).
_AMBER = (245, 158, 11)

# Layout (1× logical pixels — rendered at 2× then downscaled).
_LANE_WIDTH = 100
_LANE_GAP = 6
_HEADER_HEIGHT = 36
_BODY_HEIGHT = 400
_FOOTER_HEIGHT = 24
_MW_SCALE_WIDTH = 70
_BAND_HEIGHT = 8
_BAND_INSET = int(_LANE_WIDTH * 0.10)
_ACCENT_BAR_HEIGHT = 4
_SUPERSAMPLE = 2

# Colors.
_BG_COLOR = (30, 30, 34)
_LANE_BG = (42, 42, 46)
_HEADER_BG = (26, 26, 30)
_TEXT_COLOR = (230, 230, 230)
_TEXT_DIM = (160, 160, 160)
_SCALE_LINE = (80, 80, 85)

_ACCENT_COLORS = [
    (59, 130, 246),
    (168, 85, 247),
    (34, 197, 94),
    (249, 115, 22),
    (236, 72, 153),
    (20, 184, 166),
    (245, 158, 11),
    (99, 102, 241),
]
_STANDARD_MWS = [10, 15, 20, 25, 37, 50, 75, 100, 150, 250]


def _global_mw_range(lanes):
    """All-lane MW range, padded, mirroring front-end _getCommonMWRange; None when no band has an MW."""
    mws = [
        b.estimated_mw_kda
        for lane in lanes
        for b in lane.bands
        if getattr(b, "estimated_mw_kda", None) and b.estimated_mw_kda > 0
    ]
    if not mws:
        return None
    mw_min = min(mws) * 0.8
    mw_max = max(mws) * 1.2
    if mw_max <= mw_min:
        mw_max = mw_min * 2
    return mw_min, mw_max


def _positions_range(lanes):
    """Min/max band position_y over the lanes' bands: one scale for the lanes of a gel."""
    ys = [b.position_y for lane in lanes for b in lane.bands if getattr(b, "position_y", None) is not None]
    if not ys:
        return 0, 0
    return min(ys), max(ys)


def _gel_key(lane):
    """The gel a drawn lane is on: its analysis in a comparison, the one gel otherwise."""
    return getattr(lane, "analysis_id", None) or "gel"


def _ladder_ticks(lanes):
    """(position_y, kDa) of the ladder bands that carry an MW: the gel's own markers."""
    return sorted(
        {
            (b.position_y, b.estimated_mw_kda)
            for lane in lanes
            if (getattr(lane, "lane_type_code", None) or "").upper() == "LADDER"
            for b in lane.bands
            if getattr(b, "estimated_mw_kda", None) and getattr(b, "position_y", None) is not None
        }
    )


def _calibrated_y(mw, mw_min, mw_max, *, body_top, body_h):
    """Log10 MW → Y, HIGH MW at top."""
    log_min = math.log10(max(mw_min, 1e-6))
    log_max = math.log10(max(mw_max, mw_min * 1.0001))
    span = log_max - log_min or 1.0
    frac = (log_max - math.log10(max(mw, 1e-6))) / span
    frac = max(0.02, min(0.98, frac))
    return body_top + int(frac * body_h)


def _uncalibrated_y(pos_y, lane_min, lane_max, *, body_top, body_h):
    """position_y normalized within the lane's own range; center if degenerate."""
    frac = (pos_y - lane_min) / (lane_max - lane_min) if lane_max > lane_min else 0.5
    frac = max(0.02, min(0.98, frac))
    return body_top + int(frac * body_h)


def render_digital_gel(lanes, *, calibration, footer_field="lane_type", exclude_codes=("EMPTY",), color_key="code"):
    """Render a side-by-side digital gel.

    Args:
        lanes: iterable of LaneReportData / ComparisonLaneData.
        calibration: CalibrationReportData or None (reserved; placement uses
            per-band estimated_mw_kda, like the front-end).
        footer_field: lane attribute used for the per-column footer text.
        exclude_codes: lane_type_code values to skip entirely.
        color_key: 'code' → band fill from constants.band_colors(band_type_code).

    Returns:
        BytesIO PNG, or None when there are no drawable lanes.
    """
    from PIL import Image, ImageDraw

    from .constants import resolve_pil_font

    excl = {c.upper() for c in (exclude_codes or ())}
    drawn = [lane for lane in lanes if (getattr(lane, "lane_type_code", None) or "").upper() not in excl]
    if not drawn:
        return None

    s = _SUPERSAMPLE
    n = len(drawn)
    total_w = (_LANE_GAP + n * (_LANE_WIDTH + _LANE_GAP) + _MW_SCALE_WIDTH) * s
    total_h = (_HEADER_HEIGHT + _BODY_HEIGHT + _FOOTER_HEIGHT) * s

    img = Image.new("RGB", (total_w, total_h), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    resolve_pil_font(12 * s)
    font_small = resolve_pil_font(10 * s)

    header_h = _HEADER_HEIGHT * s
    body_h = _BODY_HEIGHT * s
    body_top = header_h
    lane_w = _LANE_WIDTH * s
    lane_gap = _LANE_GAP * s
    inset = _BAND_INSET * s
    band_h = _BAND_HEIGHT * s
    accent_h = _ACCENT_BAR_HEIGHT * s

    # A kDa axis only when every drawn band has an MW (module docstring): else every band by its position, per gel.
    every_mw = all(getattr(b, "estimated_mw_kda", None) for lane in drawn for b in lane.bands)
    mw_range = _global_mw_range(drawn) if every_mw else None
    gels = {}
    for lane in drawn:
        gels.setdefault(_gel_key(lane), []).append(lane)
    gel_ranges = {key: _positions_range(gel_lanes) for key, gel_lanes in gels.items()}

    def _band_fill(band):
        bp = band_colors(getattr(band, "band_type_code", None) or getattr(band, "band_type", None) or "OTHER")
        return bp["fill"][:3]

    for i, lane in enumerate(drawn):
        col_x = lane_gap + i * (lane_w + lane_gap)
        accent = _ACCENT_COLORS[i % len(_ACCENT_COLORS)]

        draw.rectangle([col_x, header_h, col_x + lane_w, header_h + body_h], fill=_LANE_BG)
        draw.rectangle([col_x, 0, col_x + lane_w, header_h], fill=_HEADER_BG)
        draw.rectangle([col_x, 0, col_x + lane_w, accent_h], fill=accent)

        # Header: sample name + lane number.
        # A report lane carries the page's sample (page_rows): "no sample" says so, where its lane type read as a name.
        if hasattr(lane, "readout_cells"):
            from .page_rows import sample_text

            sample = sample_text(lane)
            label = (lane.sample_name if sample == "—" else sample)[:14]
        else:
            label = (lane.sample_name or f"Lane {lane.lane_number}")[:14]
        lb = draw.textbbox((0, 0), label, font=font_small)
        draw.text((col_x + (lane_w - (lb[2] - lb[0])) // 2, accent_h + 4 * s), label, fill=_TEXT_COLOR, font=font_small)
        ln = f"L{lane.lane_number}"
        lnb = draw.textbbox((0, 0), ln, font=font_small)
        draw.text(
            (col_x + (lane_w - (lnb[2] - lnb[0])) // 2, accent_h + 4 * s + (lb[3] - lb[1]) + 2 * s),
            ln,
            fill=_TEXT_DIM,
            font=font_small,
        )

        # Amber uncalibrated indicator.
        is_calibrated = any(getattr(b, "estimated_mw_kda", None) for b in lane.bands)
        if not is_calibrated:
            r = 3 * s
            draw.ellipse(
                [col_x + lane_w - 2 * r - 2 * s, accent_h + 2 * s, col_x + lane_w - 2 * s, accent_h + 2 * s + 2 * r],
                fill=_AMBER,
            )

        lane_min, lane_max = gel_ranges[_gel_key(lane)]

        for band in lane.bands:
            mw = getattr(band, "estimated_mw_kda", None)
            pos_y = getattr(band, "position_y", None)
            if mw and mw > 0 and mw_range:
                y = _calibrated_y(mw, *mw_range, body_top=body_top, body_h=body_h)
            elif pos_y is not None:
                y = _uncalibrated_y(pos_y, lane_min, lane_max, body_top=body_top, body_h=body_h)
            else:
                y = body_top + body_h // 2

            base = _band_fill(band)
            opacity = 0.7
            pct = getattr(band, "relative_percent_lane", None)
            if pct is not None:
                opacity = max(0.4, min(1.0, pct / 40.0))
            blended = tuple(int(base[c] * opacity + _LANE_BG[c] * (1 - opacity)) for c in range(3))

            bx1, bx2 = col_x + inset, col_x + lane_w - inset
            draw.rectangle([bx1, y - band_h // 2, bx2, y + band_h // 2], fill=blended)
            highlight = tuple(min(255, c + 40) for c in blended)
            draw.rectangle([bx1, y - 1 * s, bx2, y + 1 * s], fill=highlight)

        footer = (str(getattr(lane, footer_field, "") or ""))[:14]
        if footer:
            fb = draw.textbbox((0, 0), footer, font=font_small)
            draw.text(
                (col_x + (lane_w - (fb[2] - fb[0])) // 2, header_h + body_h + 4 * s),
                footer,
                fill=_TEXT_DIM,
                font=font_small,
            )

    # MW scale on the right.
    scale_x = lane_gap + n * (lane_w + lane_gap) + 4 * s
    if mw_range:
        mw_min, mw_max = mw_range
        visible = [mw for mw in _STANDARD_MWS if mw_min <= mw <= mw_max]
        for mw in visible:
            y = _calibrated_y(mw, mw_min, mw_max, body_top=body_top, body_h=body_h)
            draw.line([(lane_gap, y), (scale_x - 2 * s, y)], fill=_SCALE_LINE, width=1 * s)
            draw.text((scale_x + 2 * s, y - 6 * s), f"{mw} kDa", fill=_TEXT_DIM, font=font_small)
    elif len(gels) == 1 and _ladder_ticks(drawn):
        # Bands by position on the one gel: its ladder bands are kDa markers at their own positions.
        lane_min, lane_max = next(iter(gel_ranges.values()))
        for pos_y, mw in _ladder_ticks(drawn):
            y = _uncalibrated_y(pos_y, lane_min, lane_max, body_top=body_top, body_h=body_h)
            draw.line([(lane_gap, y), (scale_x - 2 * s, y)], fill=_SCALE_LINE, width=1 * s)
            draw.text((scale_x + 2 * s, y - 6 * s), f"{mw:g} kDa", fill=_TEXT_DIM, font=font_small)
    else:
        # Bands by position, and no ladder band to label (or lanes of several gels, which share no scale): a tick
        # or grid line level with a band would read as an MW the lab never estimated.
        for i, text in enumerate(("No MW", "calibration")):
            draw.text((scale_x + 2 * s, body_top + 8 * s + i * 13 * s), text, fill=_TEXT_DIM, font=font_small)
    draw.text((scale_x + 2 * s, header_h - 14 * s), "MW", fill=_TEXT_COLOR, font=font_small)

    if s != 1:
        img = img.resize((total_w // s, total_h // s), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
