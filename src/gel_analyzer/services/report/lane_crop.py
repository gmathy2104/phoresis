"""A lane's crop for the reports: the outline's padded box, masked outside the outline (spec 2026-10-10 §5.1).

The report lane rows carry ``polygon`` only when the lane is read by it (the collectors apply Rule 2), so a row with a
polygon is a lane drawn by its outline and a row without one is a box.
"""

from gel_analyzer.services.lane_geometry.shape import outer_bbox, span_at


def outline_of_row(lane) -> list | None:
    """The outline of a report lane row: its polygon, else its box; None without geometry."""
    if lane.polygon:
        return [[float(x), float(y)] for x, y in lane.polygon]
    if any(v is None for v in (lane.x, lane.y, lane.width, lane.height)):
        return None
    x, y, w, h = lane.x, lane.y, lane.width, lane.height
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def top_left(outline: list) -> tuple:
    """Left end of the outline's top row: where a lane label goes (a rectangle's (x, y))."""
    y = min(p[1] for p in outline)
    return span_at(outline, y)[0], y


def bottom_centre(outline: list) -> tuple:
    """Middle of the outline's bottom row: where a name under the lane goes."""
    y = max(p[1] for p in outline)
    lo, hi = span_at(outline, y)
    return (lo + hi) / 2, y


def is_upright_box(outline: list) -> bool:
    """Four corners on two x and two y values: the outline is its own box (a rectangle, a Straight accept)."""
    return len(outline) == 4 and len({p[0] for p in outline}) == 2 and len({p[1] for p in outline}) == 2


def crop_lane(src, lane, pad_x_div: int, pad_x_min: int, pad_y_div: int, pad_y_min: int):
    """(crop, (x1, y1, x2, y2)) of the lane in the PIL image ``src``: the outline's outer box -- never a stale stored
    box -- padded by max(min, size // div) and clipped to the image; outside a polygon lane's outline the pixels take
    the crop's median colour, the gel's own background, so a tilted lane's neighbours do not show. An upright box keeps
    its padding, as every crop did before tilted lanes. None without geometry."""
    from PIL import Image, ImageDraw, ImageStat  # the report modules import PIL where they draw

    outline = outline_of_row(lane)
    if outline is None:
        return None
    x, y, w, h = outer_bbox(outline)
    pad_x, pad_y = max(pad_x_min, w // pad_x_div), max(pad_y_min, h // pad_y_div)
    box = (max(0, x - pad_x), max(0, y - pad_y), min(src.width, x + w + pad_x), min(src.height, y + h + pad_y))
    crop = src.crop(box)
    if lane.polygon and not is_upright_box(outline):
        mask = Image.new("L", crop.size, 0)
        ImageDraw.Draw(mask).polygon([(px - box[0], py - box[1]) for px, py in outline], fill=255)
        median = ImageStat.Stat(crop).median
        background = Image.new(
            crop.mode, crop.size, tuple(int(v) for v in median) if len(median) > 1 else int(median[0])
        )
        crop = Image.composite(crop, background, mask)
    return crop, box
