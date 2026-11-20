"""
Shared Pillow renderer for the annotated gel image used in reports.

Centralises the lane/band overlay rendering so the Word, PowerPoint
and (eventually) Excel exports all produce the same visual as the
live web app's read-only gel preview (`gel_viewer_standalone.css` /
`.gv-lane.*` / `.gv-band.*`).

Visual choices, in order of importance:

1. **Lane outline coloured by `lane.lane_type_code`** — SAMPLE→blue,
   LADDER→orange, CONTROL→green, EMPTY→dashed gray. Falls back to
   SAMPLE for unknown / missing codes.
2. **Band fill coloured by `band.band_type_code`** — POI→purple,
   MW_REFERENCE→orange, OTHER→green.
3. **Polygon-aware** — `draw.polygon()` whenever the lane or band
   carries an explicit polygon outline; rectangle bbox is only used
   when no polygon is provided.
4. **Lane number** — bare number with a white stroke on dark text
   at the top-left of the lane, matching the live SVG label.
5. **Band MW** — small dark-on-white pill to the right of the band,
   only when calibrated.

The font search prefers Inter (the app's own face) so
the overlay labels match the surrounding Word / PPTX body text.
"""

from enum import Enum
from io import BytesIO

from .constants import band_colors, lane_colors, resolve_pil_font
from .lane_crop import bottom_centre, top_left


class GelOverlayVariant(Enum):
    """Which lanes/bands to draw over the real gel image."""

    LANES_ONLY = "LANES_ONLY"  # lane outlines + number + sample, no bands
    KEY_BANDS = "KEY_BANDS"  # POI + CALIBRATION + all bands on CONTROL lanes
    FULL = "FULL"  # every band


def _band_visible(band, lane_code, variant):
    """Decide whether a band is drawn for the given variant."""
    if variant is GelOverlayVariant.LANES_ONLY:
        return False
    if variant is GelOverlayVariant.FULL:
        return True
    # KEY_BANDS:
    band_code = (getattr(band, "band_type_code", None) or getattr(band, "band_type", None) or "OTHER").upper()
    if (lane_code or "").upper() == "CONTROL":
        return True
    return band_code in ("POI", "CALIBRATION")


def _mw_for_band(band, lane_code, calibration, ladder_lane_number, lane_number=None):
    """MW for the band's pill: calibration.band_matches first, then estimated_mw_kda.

    Only the specific calibration ladder lane (identified by ladder_lane_number)
    receives MW pills from calibration.band_matches.  All other LADDER lanes
    (multi-ladder gels) fall back to band.estimated_mw_kda.
    """
    if (
        calibration is not None
        and (lane_code or "").upper() == "LADDER"
        and (ladder_lane_number is None or lane_number == ladder_lane_number)
    ):
        matches = getattr(calibration, "band_matches", None) or []
        bid = str(getattr(band, "band_id", "") or "")
        by = getattr(band, "position_y", None)
        # Exact band_id match wins.
        for m in matches:
            if bid and str(m.get("band_id")) == bid:
                return m.get("mw_kda")
        # Else nearest position_y.
        if by is not None and matches:
            best = min(
                matches,
                key=lambda m: abs((m.get("position_y") or 0) - by),
            )
            return best.get("mw_kda")
    return getattr(band, "estimated_mw_kda", None)


def _draw_dashed_polygon(draw, points, color, width=2, dash=6, gap=4):
    """Pillow has no native dashed-stroke; emulate it segment by segment."""
    if len(points) < 2:
        return
    closed = points + [points[0]]
    for i in range(len(closed) - 1):
        x0, y0 = closed[i]
        x1, y1 = closed[i + 1]
        seg_len = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if seg_len <= 0:
            continue
        ux, uy = (x1 - x0) / seg_len, (y1 - y0) / seg_len
        pos = 0.0
        while pos < seg_len:
            d_end = min(pos + dash, seg_len)
            draw.line(
                [(x0 + ux * pos, y0 + uy * pos), (x0 + ux * d_end, y0 + uy * d_end)],
                fill=color,
                width=width,
            )
            pos = d_end + gap


def _shape_points(x, y, w, h, polygon):
    """Return a polygon-points list — original polygon when supplied,
    else the rectangle's four corners.
    """
    if polygon and len(polygon) >= 3:
        return [(int(p[0]), int(p[1])) for p in polygon]
    if any(v is None for v in (x, y, w, h)):
        return None
    return [(int(x), int(y)), (int(x + w), int(y)), (int(x + w), int(y + h)), (int(x), int(y + h))]


def render_gel_overlay(image_source, lanes, *, variant, calibration=None):
    """Render lane + band overlay onto a gel image.

    Args:
        image_source: anything PIL.Image.open accepts (a Django FieldFile
            such as gel_image.display_file, or a path).
        lanes: iterable of objects exposing lane_type_code, lane_number,
            sample_name, x/y/width/height, polygon (optional) and bands.
        variant: GelOverlayVariant — LANES_ONLY / KEY_BANDS / FULL.
        calibration: optional CalibrationReportData; its band_matches are the
            authoritative MW-pill source for the ladder lane.

    Returns:
        BytesIO PNG, or None when the source cannot be opened.
    """
    from PIL import Image, ImageDraw

    try:
        img = Image.open(image_source).convert("RGBA")
    except Exception:
        return None

    band_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lane_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band_layer)
    lane_draw = ImageDraw.Draw(lane_layer)

    font = resolve_pil_font(max(14, img.width // 80))
    font_small = resolve_pil_font(max(11, img.width // 100))

    lane_stroke_w = max(3, img.width // 400)
    band_stroke_w = max(2, img.width // 600)

    label_ink = (15, 23, 42, 255)
    label_stroke = (255, 255, 255, 235)
    mw_pill_bg = (255, 255, 255, 220)
    mw_pill_fg = (15, 23, 42, 255)

    ladder_lane_number = getattr(calibration, "ladder_lane_number", None)

    for lane in lanes:
        lane_polygon = getattr(lane, "polygon", None)
        lane_pts = _shape_points(lane.x, lane.y, lane.width, lane.height, lane_polygon)
        if lane_pts is None:
            continue

        lane_code = getattr(lane, "lane_type_code", None) or getattr(lane, "lane_type", None) or "SAMPLE"
        palette = lane_colors(lane_code)
        fill = palette["fill"]
        stroke = palette["stroke"]
        dashed = palette["dashed"]

        band_draw.polygon(lane_pts, fill=fill)

        lane_number = getattr(lane, "lane_number", None)
        for band in getattr(lane, "bands", []):
            if not _band_visible(band, lane_code, variant):
                # KEY_BANDS hides MW_REFERENCE fill/outline on LADDER lanes, but
                # the spec says MW pills should still appear.  Draw the pill only.
                if variant is GelOverlayVariant.KEY_BANDS and (lane_code or "").upper() == "LADDER":
                    mw = _mw_for_band(band, lane_code, calibration, ladder_lane_number, lane_number)
                    if mw:
                        band_polygon = getattr(band, "polygon", None)
                        band_pts = _shape_points(
                            band.bbox_x, band.bbox_y, band.bbox_width, band.bbox_height, band_polygon
                        )
                        if band_pts is not None:
                            mw_label = f"{mw:.0f} kDa"
                            mbbox = band_draw.textbbox((0, 0), mw_label, font=font_small)
                            mw_w = mbbox[2] - mbbox[0]
                            mw_h = mbbox[3] - mbbox[1]
                            rx = max(p[0] for p in band_pts) + 4
                            ry = (min(p[1] for p in band_pts) + max(p[1] for p in band_pts)) // 2 - mw_h // 2
                            band_draw.rectangle(
                                [rx - 2, ry - 2, rx + mw_w + 4, ry + mw_h + 2],
                                fill=mw_pill_bg,
                                outline=(15, 23, 42, 80),
                            )
                            band_draw.text((rx + 1, ry), mw_label, fill=mw_pill_fg, font=font_small)
                continue
            band_polygon = getattr(band, "polygon", None)
            band_pts = _shape_points(band.bbox_x, band.bbox_y, band.bbox_width, band.bbox_height, band_polygon)
            if band_pts is None:
                continue
            band_code = getattr(band, "band_type_code", None) or getattr(band, "band_type", None) or "OTHER"
            bp = band_colors(band_code)
            band_draw.polygon(band_pts, fill=bp["fill"])
            for i in range(len(band_pts)):
                a, b = band_pts[i], band_pts[(i + 1) % len(band_pts)]
                band_draw.line([a, b], fill=bp["stroke"], width=band_stroke_w)

            mw = _mw_for_band(band, lane_code, calibration, ladder_lane_number, lane_number)
            if mw:
                mw_label = f"{mw:.0f} kDa"
                mbbox = band_draw.textbbox((0, 0), mw_label, font=font_small)
                mw_w = mbbox[2] - mbbox[0]
                mw_h = mbbox[3] - mbbox[1]
                rx = max(p[0] for p in band_pts) + 4
                ry = (min(p[1] for p in band_pts) + max(p[1] for p in band_pts)) // 2 - mw_h // 2
                band_draw.rectangle(
                    [rx - 2, ry - 2, rx + mw_w + 4, ry + mw_h + 2],
                    fill=mw_pill_bg,
                    outline=(15, 23, 42, 80),
                )
                band_draw.text((rx + 1, ry), mw_label, fill=mw_pill_fg, font=font_small)

        if dashed:
            _draw_dashed_polygon(lane_draw, lane_pts, stroke, width=lane_stroke_w, dash=8, gap=5)
        else:
            for i in range(len(lane_pts)):
                a, b = lane_pts[i], lane_pts[(i + 1) % len(lane_pts)]
                lane_draw.line([a, b], fill=stroke, width=lane_stroke_w)

        label = str(lane.lane_number)
        # Inside the left end of the lane's top row (a rectangle's top-left corner): the minimum x over all the
        # corners is a tilted lane's foot, left of its top.
        top_x, top_y = top_left(lane_pts)
        anchor_x = int(top_x) + 4
        anchor_y = int(top_y) + 4
        lane_draw.text(
            (anchor_x, anchor_y),
            label,
            fill=label_ink,
            font=font,
            stroke_width=2,
            stroke_fill=label_stroke,
        )

        sample = getattr(lane, "sample_name", "") or ""
        if sample and not all(v is not None and v >= 0 for v in (lane.x,)):
            sample = ""
        if sample:
            short = sample[:24]
            bbox = lane_draw.textbbox((0, 0), short, font=font_small)
            sw, sh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            # Under the middle of the lane's bottom row: a tilted lane's foot is not under its box's centre.
            foot_x, foot_y = bottom_centre(lane_pts)
            cx = int(foot_x) - sw // 2
            cy = int(foot_y) + 4
            pad = 3
            lane_draw.rectangle([cx - pad, cy, cx + sw + pad, cy + sh + 4], fill=(255, 255, 255, 210))
            lane_draw.text((cx, cy + 2), short, fill=mw_pill_fg, font=font_small)

    composed = Image.alpha_composite(img, band_layer)
    composed = Image.alpha_composite(composed, lane_layer).convert("RGB")
    buf = BytesIO()
    composed.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf
