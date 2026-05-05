"""
Shared Pillow renderer for the annotated gel image used in reports.

Centralises the lane/band overlay rendering so the Word, PowerPoint
and (eventually) Excel exports all produce the same visual as the
live web app's read-only gel preview (``gel-preview.js`` +
``gel_viewer_standalone.css`` / ``.gv-lane.*`` / ``.gv-band.*``).

Visual choices, in order of importance:

1. **Lane outline coloured by ``lane.lane_type_code``** — SAMPLE→blue,
   LADDER→orange, CONTROL→green, EMPTY→dashed gray. Mirrors
   gel_viewer_standalone.css :387-406. Falls back to SAMPLE for
   unknown / missing codes.
2. **Band fill coloured by ``band.band_type_code``** — POI→purple,
   MW_REFERENCE→orange, OTHER→green. Mirrors the corresponding
   ``.gv-band.*`` rules.
3. **Polygon-aware** — ``draw.polygon()`` whenever the lane or band
   carries an explicit polygon outline; rectangle bbox is only used
   when no polygon is provided.
4. **Lane number** — bare number with a white stroke on dark text
   (``PHORESIS_INK``) at the top-left of the lane, matching the
   live SVG label. No "L" prefix, no black pill (which the original
   code did and which made the report look dated).
5. **Band MW** — small dark-on-white pill to the right of the band,
   only when calibrated.
"""

from __future__ import annotations

from io import BytesIO

from .constants import band_colors, lane_colors


def _font_pair(image_width: int):
    """Pick a sans-serif TrueType pair sized to the image.

    Tries Inter / Segoe UI / Arial in order; falls back to Pillow's
    default bitmap font if none of the truetype faces are reachable
    (which happens in some sandboxed CI runners).
    """
    from PIL import ImageFont

    big = max(14, image_width // 80)
    small = max(11, image_width // 100)
    candidates = [
        "Inter-Regular.ttf",
        "Inter.ttf",
        "segoeui.ttf",
        "arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, big), ImageFont.truetype(name, small)
        except OSError:
            continue
    default = ImageFont.load_default()
    return default, default


def _draw_dashed_polygon(draw, points, color, width: int = 2, dash: int = 6, gap: int = 4):
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


def render_gel_overlay(image_source, lanes, *, draw_band_overlay: bool = True) -> BytesIO | None:
    """Render lane + band overlay onto a gel image.

    Args:
        image_source: Anything PIL.Image.open accepts — typically a
            Django FieldFile (``gel_image.display_file``) or a path.
        lanes: Iterable of objects exposing ``lane_type_code``,
            ``lane_number``, ``sample_name``, ``x``/``y``/``width``/``height``,
            ``polygon`` (optional) and ``bands`` — each band exposing
            ``band_type_code``, ``polygon`` (optional), bbox attrs and
            ``estimated_mw_kda``.
        draw_band_overlay: When ``False``, only the lane outlines are
            drawn (used by the digital-gel section that has its own
            band rendering).

    Returns:
        BytesIO with a PNG-encoded RGB image, or ``None`` when the
        source image cannot be opened.
    """
    from PIL import Image, ImageDraw

    try:
        img = Image.open(image_source).convert("RGBA")
    except Exception:
        return None

    # Two overlay layers so lane outlines paint ON TOP of band rectangles
    # (otherwise full-width bands overwrite the lane's vertical edge
    # strokes and the lanes look invisible — confirmed in the report
    # rendering). Bands go on the lower layer; lane outline + label go
    # on the upper one. Both alpha-composite onto the original gel.
    band_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lane_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band_layer)
    lane_draw = ImageDraw.Draw(lane_layer)

    font, font_small = _font_pair(img.width)

    # Stroke widths scale with the gel image — a 1500px-wide gel needs a
    # 4-5px lane outline to read; a 600px crop only needs 2-3px.
    lane_stroke_w = max(3, img.width // 400)
    band_stroke_w = max(2, img.width // 600)

    label_ink = (15, 23, 42, 255)            # PHORESIS_INK
    label_stroke = (255, 255, 255, 235)
    mw_pill_bg = (255, 255, 255, 220)
    mw_pill_fg = (15, 23, 42, 255)

    for lane in lanes:
        lane_pts = _shape_points(lane.x, lane.y, lane.width, lane.height, lane.polygon)
        if lane_pts is None:
            continue

        palette = lane_colors(getattr(lane, "lane_type_code", None) or "SAMPLE")
        fill = palette["fill"]
        stroke = palette["stroke"]
        dashed = palette["dashed"]

        # Lane fill goes on the BAND layer so band fills can sit on top
        # of it. The lane's outline + label go on the LANE layer (drawn
        # below — so it ends up visually above the bands).
        band_draw.polygon(lane_pts, fill=fill)

        # Bands first (still on the band layer)
        if draw_band_overlay:
            for band in getattr(lane, "bands", []):
                band_pts = _shape_points(
                    band.bbox_x, band.bbox_y, band.bbox_width, band.bbox_height, band.polygon
                )
                if band_pts is None:
                    continue
                bp = band_colors(getattr(band, "band_type_code", None) or "OTHER")
                band_draw.polygon(band_pts, fill=bp["fill"])
                for i in range(len(band_pts)):
                    a, b = band_pts[i], band_pts[(i + 1) % len(band_pts)]
                    band_draw.line([a, b], fill=bp["stroke"], width=band_stroke_w)

                if band.estimated_mw_kda:
                    mw_label = f"{band.estimated_mw_kda:.0f} kDa"
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

        # Lane outline on the upper layer so band rectangles cannot
        # overdraw the vertical edge strokes.
        if dashed:
            _draw_dashed_polygon(lane_draw, lane_pts, stroke, width=lane_stroke_w, dash=8, gap=5)
        else:
            for i in range(len(lane_pts)):
                a, b = lane_pts[i], lane_pts[(i + 1) % len(lane_pts)]
                lane_draw.line([a, b], fill=stroke, width=lane_stroke_w)

        # Lane number label
        label = str(lane.lane_number)
        anchor_x = min(p[0] for p in lane_pts) + 4
        anchor_y = min(p[1] for p in lane_pts) + 4
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
            cx = lane.x + (lane.width - sw) // 2
            cy = lane.y + lane.height + 4
            pad = 3
            lane_draw.rectangle(
                [cx - pad, cy, cx + sw + pad, cy + sh + 4], fill=(255, 255, 255, 210)
            )
            lane_draw.text((cx, cy + 2), short, fill=mw_pill_fg, font=font_small)

    composed = Image.alpha_composite(img, band_layer)
    composed = Image.alpha_composite(composed, lane_layer).convert("RGB")
    buf = BytesIO()
    composed.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf
