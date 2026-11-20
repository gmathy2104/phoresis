"""
The gel as the app's whole-gel views draw it, for the reports: a static picture of the PD dashboard's "Full gel" tile.

``pdd-full-gel.js`` paints one gel whole: every lane outlined, above each lane a colour bar, its number and a slanted
label, under each lane its value, a legend; the sample identity card (``sample-lane-gel.js``) adds the kDa axis of the
ladder. A PowerPoint holds a picture and the production server runs no browser, so this module draws the same look with
Pillow, from what the report already holds: each lane's outline (``lane_crop.outline_of_row``, Rule 2 applied by the
collectors), its bands with their role in the readout (``analysis_detail.band_role_map``, through ``page_rows``), the
analysis page's cells (``page_rows``) and the ladder's kDa ticks (``page_rows.gel_mw_ticks``: ``sample_gels``' rule).
It draws; it computes no value.

The dashboard tile's own producer (``full_gel.build_full_gel``) is not read: it needs the dashboard's sheets as its
access scope. Both print the analysis page's cells (``analysis_detail.lane_rows``) and the same value row
(``page_rows.HEADLINE_KEYS``).

A lane slide draws its lane as the sample identity card does (:func:`render_lane_figure`): put forward on its
whole gel, its bands named, its stored profile beside the gel on the same rows -- from the card's own producer,
``sample_gels.lane_strip_entries``.

Variants (``gel_overlay.GelOverlayVariant``): LANES_ONLY draws no band; FULL every band by its type; KEY_BANDS the bands
the readout is read from -- on a purity gel the POI and calibration bands and a control lane's bands, on a western the
bands by their role (HMWS / main band / LMWS; HCP bands, the POI left out dashed).
"""

from __future__ import annotations

import math
from io import BytesIO

from .constants import band_colors, lane_colors, resolve_pil_font
from .gel_overlay import GelOverlayVariant
from .lane_crop import outline_of_row
from .page_rows import HEADLINE_KEYS, sample_text

# The roles' colours: the pages' swatches (analysis_detail.reading_guide's tokens).
ROLE_COLORS = {
    "aggregate": (245, 158, 11),
    "main": (168, 85, 247),
    "clipping": (56, 189, 248),
    "hcp": (34, 197, 94),
    "left_out": (156, 163, 175),
}
SATURATED = (217, 119, 6)
INK = (36, 38, 43)
MUTED = (107, 114, 128)
TICK = (156, 163, 175)
# The value row's caption, by readout.
VALUE_CAPTIONS = {"PURITY": "Purity %", "MOLECULE_VARIANTS": "Main band %", "HOST_CELL_PROTEINS": "HCP % of ref."}
BADGES = {"LADDER": "MW", "CONTROL": "CTRL", "CALIBRATION": "CAL", "EMPTY": ""}

# The picture's size: the "Image and Text 2" layout's picture area (8.26 x 5.24 in) at 250 dpi.
TARGET_W, TARGET_H = 2065, 1310
LABEL_ANGLE = 40


def value_text(readout: str, lane) -> tuple[str, bool]:
    """The lane's value as the row under the gel prints it: (text, is_reason) -- the number without its unit, else a
    short form of the page's reason; ("", False) for a lane the readout does not read."""
    key, _words = HEADLINE_KEYS.get(readout, (None, ""))
    cell = lane.readout_cells.get(key) if key else None
    if cell is None:
        return "", False
    if lane.readout_numbers.get(key) is None:
        reason = cell.get("reason") or ""
        return ("no POI" if reason == "no POI band" else "—"), True
    return cell["text"].replace(" %", ""), False


def _band_style(band, lane_code, variant, readout):
    """(stroke RGB, fill alpha, dashed) of a band in this variant, or None when the variant does not draw it."""
    code = (band.band_type_code or "OTHER").upper()
    if variant is GelOverlayVariant.LANES_ONLY:
        return None
    if variant is GelOverlayVariant.KEY_BANDS and readout in ("MOLECULE_VARIANTS", "HOST_CELL_PROTEINS"):
        role = getattr(band, "role", None)
        if role is None:
            return None
        return ROLE_COLORS[role], 30 if role == "left_out" else 60, role == "left_out"
    if variant is GelOverlayVariant.KEY_BANDS and code not in ("POI", "CALIBRATION") and lane_code != "CONTROL":
        return None
    stroke = band_colors(code)["stroke"][:3]
    return stroke, 55, False


def _dashed(draw, points, color, width, dash=10, gap=7):
    closed = list(points) + [points[0]]
    for (x0, y0), (x1, y1) in zip(closed, closed[1:], strict=False):
        length = math.hypot(x1 - x0, y1 - y0)
        if not length:
            continue
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        pos = 0.0
        while pos < length:
            end = min(pos + dash, length)
            draw.line([(x0 + ux * pos, y0 + uy * pos), (x0 + ux * end, y0 + uy * end)], fill=color, width=width)
            pos = end + gap


def _band_points(band):
    if band.polygon and len(band.polygon) >= 3:
        return [(float(x), float(y)) for x, y in band.polygon]
    if None in (band.bbox_x, band.bbox_y, band.bbox_width, band.bbox_height):
        return None
    x, y, w, h = band.bbox_x, band.bbox_y, band.bbox_width, band.bbox_height
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def render_gel_figure(image_source, lanes, *, variant, readout: str, ticks=()) -> BytesIO | None:
    """The gel whole, in the "Full gel" tile's look, as a PNG; None when the image cannot be opened or has no lane.

    ``lanes``: the report's lanes of ONE gel (``LaneReportData`` with the page's cells). ``ticks``: ``[{mw_kda, y}]``
    in image pixels, the ladder's markers; none draws no axis.
    """
    from PIL import Image, ImageDraw

    try:
        photo = Image.open(image_source).convert("RGB")
    except Exception:
        return None
    outlines = [(lane, outline_of_row(lane)) for lane in lanes]
    outlines = [(lane, outline) for lane, outline in outlines if outline]
    if not outlines:
        return None

    # The photo, cropped to its lanes.
    margin = 12
    xs = [x for _lane, outline in outlines for x, _y in outline]
    ys = [y for _lane, outline in outlines for _x, y in outline]
    x0, y0 = max(0, min(xs) - margin), max(0, min(ys) - margin)
    x1, y1 = min(photo.width, max(xs) + margin), min(photo.height, max(ys) + margin)
    crop = photo.crop((int(x0), int(y0), int(x1), int(y1)))

    label_font, number_font, value_font = resolve_pil_font(26), resolve_pil_font(24), resolve_pil_font(24)
    axis_font = resolve_pil_font(22)
    labels = []
    for lane, _outline in outlines:
        code = (lane.lane_type_code or "SAMPLE").upper()
        badge = "REF" if lane.is_reference else BADGES.get(code, "")
        text = badge if code in ("LADDER", "EMPTY") else f"{badge} {sample_text(lane)}".strip()
        labels.append(text[:24])
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    widest = max((probe.textlength(text, font=label_font) for text in labels), default=0)
    sin, cos = math.sin(math.radians(LABEL_ANGLE)), math.cos(math.radians(LABEL_ANGLE))
    header_h = int(min(widest * sin + 26 * cos, 320)) + 64
    footer_h = 64 if readout in VALUE_CAPTIONS else 16
    caption = VALUE_CAPTIONS.get(readout, "")
    # Left of the photo: the kDa labels, and the value row's caption beside the values.
    axis_w = int(max(120 if ticks else 24, probe.textlength(caption, font=axis_font) + 24 if caption else 0))
    pad_right = int(min(widest * cos, 260)) + 16  # the last lane's label leans past the photo's right edge

    scale = min((TARGET_W - axis_w - pad_right) / crop.width, (TARGET_H - header_h - footer_h) / crop.height)
    photo_w, photo_h = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
    width, height = axis_w + photo_w + pad_right, header_h + photo_h + footer_h
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(crop.resize((photo_w, photo_h), Image.Resampling.LANCZOS), (axis_w, header_h))

    def at(x, y):
        return axis_w + (x - x0) * scale, header_h + (y - y0) * scale

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    text_draw = ImageDraw.Draw(canvas)

    for (lane, outline), label in zip(outlines, labels, strict=False):
        code = (lane.lane_type_code or "SAMPLE").upper()
        colour = lane_colors(code)
        stroke = colour["stroke"][:3]
        points = [at(x, y) for x, y in outline]

        # Bands, by the variant and the readout; a saturated band outlined amber and marked.
        for band in lane.bands:
            style = _band_style(band, code, variant, readout)
            band_points = _band_points(band)
            if style is None or band_points is None:
                continue
            band_stroke, alpha, dashed = style
            pts = [at(x, y) for x, y in band_points]
            draw.polygon(pts, fill=band_stroke + (alpha,))
            if dashed:
                _dashed(draw, pts, band_stroke + (255,), 2, dash=6, gap=5)
            else:
                draw.polygon(pts, outline=band_stroke + (255,), width=2)
            if band.saturated:
                draw.polygon(pts, outline=SATURATED + (255,), width=5)
                right = max(p[0] for p in pts)
                mid = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
                draw.polygon([(right + 6, mid + 10), (right + 18, mid - 12), (right + 30, mid + 10)], fill=SATURATED)
                draw.text((right + 15, mid + 1), "!", fill=(255, 255, 255), font=resolve_pil_font(16), anchor="mm")

        # The lane's outline, as drawn (a tilted lane keeps its slant).
        if colour["dashed"]:
            _dashed(draw, points, stroke + (220,), 3)
        else:
            draw.polygon(points, outline=stroke + (235,), width=3)

        # Above the lane: its colour bar, its number, its label slanted up and right.
        top_y = min(p[1] for p in points)
        top = [p for p in points if abs(p[1] - top_y) < 1e-6] or points
        left, right = min(p[0] for p in top), max(p[0] for p in top)
        centre = (left + right) / 2
        bar_y = header_h - 14
        text_draw.rectangle([left + 2, bar_y, right - 2, bar_y + 8], fill=stroke)
        text_draw.text((centre, bar_y - 6), str(lane.lane_number), fill=MUTED, font=number_font, anchor="mb")
        if label:
            ink = INK if code == "SAMPLE" and not lane.is_reference else stroke
            box = probe.textbbox((0, 0), label, font=label_font)
            tile = Image.new("RGBA", (box[2] + 6, box[3] + 8), (255, 255, 255, 0))
            ImageDraw.Draw(tile).text((2, 2), label, fill=ink + (255,), font=label_font)
            turned = tile.rotate(LABEL_ANGLE, expand=True, resample=Image.Resampling.BICUBIC)
            canvas.paste(turned, (int(centre - tile.height * sin / 2), int(bar_y - 36 - turned.height)), turned)

        # Under the lane: the page's value for the readout.
        text, is_reason = value_text(readout, lane)
        if text:
            bottom_y = max(p[1] for p in points)
            text_draw.text(
                (centre, bottom_y + 12),
                text,
                fill=MUTED if is_reason else INK,
                font=resolve_pil_font(20) if is_reason else value_font,
                anchor="mt",
            )

    canvas.paste(layer, (0, 0), layer)
    ink_draw = ImageDraw.Draw(canvas)
    if caption:
        ink_draw.text((axis_w - 8, header_h + photo_h + 12), caption, fill=MUTED, font=axis_font, anchor="rt")
    # The ladder's markers, left of the photo.
    if ticks:
        ink_draw.text((axis_w - 10, header_h - 8), "kDa", fill=MUTED, font=axis_font, anchor="rb")
        for tick in ticks:
            _x, y = at(x0, tick["y"])
            if not header_h <= y <= header_h + photo_h:
                continue
            ink_draw.line([(axis_w - 8, y), (axis_w, y)], fill=TICK, width=2)
            mw = tick["mw_kda"]
            ink_draw.text(
                (axis_w - 12, y), f"{mw:g}" if mw >= 10 else f"{mw:.1f}", fill=MUTED, font=axis_font, anchor="rm"
            )

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def legend_lines(variant, readout: str, *, has_ticks: bool, has_saturated: bool) -> list[str]:
    """What the picture's colours, marks and value row mean, for the slide's text beside it."""
    lines = ["Lane outlines: blue sample · green control · orange ladder · red standard · dashed grey empty"]
    if variant is GelOverlayVariant.FULL:
        lines.append("Bands: purple POI · green other · orange MW reference · red calibration")
    elif variant is GelOverlayVariant.KEY_BANDS:
        if readout == "MOLECULE_VARIANTS":
            lines.append("Bands by their role: amber HMWS · purple main band · blue LMWS")
        elif readout == "HOST_CELL_PROTEINS":
            lines.append("Bands by their role: green HCP band (counted) · dashed grey POI band (left out)")
        else:
            lines.append("Bands: the POI and calibration bands, and a control lane's bands")
    if has_saturated:
        lines.append("Amber outline and ! : a saturated band (its pixels clip at the end of the scale)")
    if readout in VALUE_CAPTIONS:
        lines.append(f"Under each lane: {VALUE_CAPTIONS[readout]}, the analysis page's value")
    if has_ticks:
        lines.append("kDa: the ladder's markers")
    return lines


LANE_ACCENT = (37, 99, 235)
OTHER_LANE = (148, 163, 184)
POI_FILL = (168, 85, 247)
PROFILE_INK = (71, 85, 105)


def _band_colour(band, readout):
    """A band's colour on the lane figure: its role on a western (as the page colours it), else its type."""
    role = getattr(band, "role", None)
    if readout in ("MOLECULE_VARIANTS", "HOST_CELL_PROTEINS") and role:
        return ROLE_COLORS[role], role == "left_out"
    return band_colors((band.band_type_code or "OTHER").upper())["stroke"][:3], False


def render_lane_figure(image_source, entry, lane, *, readout: str) -> BytesIO | None:
    """One lane put forward on its whole gel, in the sample identity card's look (``sample-lane-gel.js``), as a PNG.

    Every lane of the gel outlined and numbered, a veil over all but this one, its bands named as the page names them
    (B1 from the top) and coloured by their type or, on a western, their role, a saturated one in amber; its pill under
    it; the kDa of the ladder nearest it on the left; its stored densitometry profile beside the gel, on the same rows,
    the POI's area filled. ``entry``: the lane's ``sample_gels.lane_strip_entries`` entry -- the card's own producer
    (every lane's outline, the ticks, the profile); ``lane``: the report lane (its bands' names, saturation, roles).
    None when the image cannot be opened.
    """
    from PIL import Image, ImageDraw

    try:
        photo = Image.open(image_source).convert("RGB")
    except Exception:
        return None
    outlines = {other["id"]: other for other in entry["lanes"]}
    own = outlines.get(entry["lane_id"])
    if own is None:
        return None

    margin = 12
    xs = [x for other in outlines.values() for x, _y in other["outline"]]
    ys = [y for other in outlines.values() for _x, y in other["outline"]]
    x0, y0 = max(0, min(xs) - margin), max(0, min(ys) - margin)
    x1, y1 = min(photo.width, max(xs) + margin), min(photo.height, max(ys) + margin)
    crop = photo.crop((int(x0), int(y0), int(x1), int(y1)))

    ticks = entry.get("mw_ticks") or []
    small, label_font, pill_font = resolve_pil_font(20), resolve_pil_font(22), resolve_pil_font(24)
    header_h, footer_h = 44, 70
    axis_w = 96 if ticks else 60  # the band names sit left of the lane: room for "B12 !" on the first lane
    scale = min(1500 / crop.width, (1250 - header_h - footer_h) / crop.height)
    photo_w, photo_h = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
    gap, profile_w = 28, int(photo_w * 0.26)
    width, height = axis_w + photo_w + gap + profile_w + 24, header_h + photo_h + footer_h
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(crop.resize((photo_w, photo_h), Image.Resampling.LANCZOS), (axis_w, header_h))

    def at(x, y):
        return axis_w + (x - x0) * scale, header_h + (y - y0) * scale

    own_points = [at(x, y) for x, y in own["outline"]]

    # The veil over everything but the lane (the card's dimOthers).
    veil = Image.new("L", (photo_w, photo_h), 150)
    ImageDraw.Draw(veil).polygon([(x - axis_w, y - header_h) for x, y in own_points], fill=0)
    canvas.paste(Image.new("RGB", (photo_w, photo_h), (255, 255, 255)), (axis_w, header_h), veil)

    draw = ImageDraw.Draw(canvas)
    for other in outlines.values():
        points = [at(x, y) for x, y in other["outline"]]
        top_y = min(p[1] for p in points)
        top = [p for p in points if abs(p[1] - top_y) < 1e-6] or points
        centre = (min(p[0] for p in top) + max(p[0] for p in top)) / 2
        is_self = other["id"] == entry["lane_id"]
        if not is_self:
            draw.polygon(points, outline=OTHER_LANE, width=2)
        text = "MW" if other["lane_type"] == "LADDER" else str(other["lane_number"])
        draw.text(
            (centre, header_h - 8),
            text,
            fill=LANE_ACCENT if is_self else MUTED,
            font=label_font if is_self else small,
            anchor="mb",
        )

    # The lane's bands, named as the page names them.
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(layer)
    lane_left = min(p[0] for p in own_points)
    named_at = []  # the rows a band name is written on: a name over another is left out (the table names them all)
    for band in lane.bands:
        band_points = _band_points(band)
        if band_points is None:
            continue
        pts = [at(x, y) for x, y in band_points]
        colour, dashed = _band_colour(band, readout)
        band_draw.polygon(pts, fill=colour + (45,))
        if dashed:
            _dashed(band_draw, pts, colour + (255,), 3, dash=8, gap=6)
        else:
            stroke = SATURATED if band.saturated else colour
            band_draw.polygon(pts, outline=stroke + (255,), width=5 if band.saturated else 3)
        mid = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        if any(abs(mid - row) < 20 for row in named_at) and not band.saturated:
            continue
        named_at.append(mid)
        name = (band.name or "") + (" !" if band.saturated else "")
        ink = SATURATED if band.saturated else INK
        band_draw.text((lane_left - 8, mid), name, fill=ink + (255,), font=small, anchor="rm")
    canvas.paste(layer, (0, 0), layer)
    draw = ImageDraw.Draw(canvas)
    draw.polygon(own_points, outline=LANE_ACCENT, width=4)

    # The pill under the lane: its number and sample.
    bottom_y = max(p[1] for p in own_points)
    bottom = [p for p in own_points if abs(p[1] - bottom_y) < 1e-6] or own_points
    centre = (min(p[0] for p in bottom) + max(p[0] for p in bottom)) / 2
    pill = f"L{lane.lane_number} · {sample_text(lane)}"
    pill_w = draw.textlength(pill, font=pill_font) + 28
    left = min(max(centre - pill_w / 2, axis_w), axis_w + photo_w - pill_w)
    top = header_h + photo_h + 12
    draw.rounded_rectangle([left, top, left + pill_w, top + 38], radius=19, fill=LANE_ACCENT)
    draw.text((left + pill_w / 2, top + 19), pill, fill=(255, 255, 255), font=pill_font, anchor="mm")

    # The ladder's markers.
    if ticks:
        draw.text((axis_w - 10, header_h - 8), "kDa", fill=MUTED, font=small, anchor="rb")
        for tick in ticks:
            _x, y = at(x0, tick["y"])
            if header_h <= y <= header_h + photo_h:
                draw.line([(axis_w - 8, y), (axis_w, y)], fill=TICK, width=2)
                mw = tick["mw_kda"]
                label = f"{mw:g}" if mw >= 10 else f"{mw:.1f}"
                draw.text((axis_w - 12, y), label, fill=MUTED, font=small, anchor="rm")

    # The lane's stored profile beside the gel, on the gel's own rows.
    px0 = axis_w + photo_w + gap
    draw.line([(px0, header_h), (px0, header_h + photo_h)], fill=TICK, width=2)
    profile = entry.get("profile")
    if profile and profile.get("y"):
        peak = max(profile["intensity"]) or 1

        def px(value):
            return px0 + max(value, 0) / peak * profile_w

        fill = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        fill_draw = ImageDraw.Draw(fill)
        for band in lane.bands:
            if (band.band_type_code or "").upper() != "POI" or band.bbox_y is None:
                continue
            seg = [
                (px(v), at(x0, y)[1])
                for y, v in zip(profile["y"], profile["intensity"], strict=False)
                if band.bbox_y <= y <= band.bbox_y + band.bbox_height
            ]
            if len(seg) > 1:
                fill_draw.polygon([(px0, seg[0][1])] + seg + [(px0, seg[-1][1])], fill=POI_FILL + (80,))
        canvas.paste(fill, (0, 0), fill)
        draw = ImageDraw.Draw(canvas)
        line = [(px(v), at(x0, y)[1]) for y, v in zip(profile["y"], profile["intensity"], strict=False)]
        draw.line(line, fill=PROFILE_INK, width=2)
        draw.text((px0 + profile_w / 2, header_h + photo_h + 12), "lane profile", fill=MUTED, font=small, anchor="mt")
    else:
        middle = header_h + photo_h / 2
        draw.text((px0 + profile_w / 2, middle), "no densitometry yet", fill=MUTED, font=small, anchor="mm")

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
