"""A lane as an axis: x at a reference height and a slope (px of x per px of y), cut into a quadrilateral -- and the
rules that keep a lane's box and polygon in agreement (spec 2026-10-10 §4).

Plain values in, plain values out (no Django): the bench loads this package standalone.
"""

from __future__ import annotations

import math

BOX_KEYS = ("x", "y", "width", "height")


class GeometryRefused(ValueError):
    """A lane geometry the server will not store, with what is wrong."""


def quad_from_axis(x_ref: float, y_ref: float, slope: float, width: float, y_top: float, y_bottom: float) -> list:
    """TL, TR, BR, BL of the lane whose axis passes through (x_ref, y_ref): horizontal top and bottom, sides parallel
    to the axis, ``width`` wide on every row. Not clipped: whoever writes it clips last (spec §3)."""
    half = width / 2
    x_top = x_ref + slope * (y_top - y_ref)
    x_bottom = x_ref + slope * (y_bottom - y_ref)
    return [[x_top - half, y_top], [x_top + half, y_top], [x_bottom + half, y_bottom], [x_bottom - half, y_bottom]]


def span_at(polygon: list, y: float) -> tuple[float, float] | None:
    """The polygon's x-interval on row ``y`` (the outer interval for a non-convex polygon); None off the polygon."""
    xs = []
    count = len(polygon)
    for i in range(count):
        (x0, y0), (x1, y1) = polygon[i], polygon[(i + 1) % count]
        if y0 == y1:
            if y == y0:
                xs.extend((x0, x1))
            continue
        if min(y0, y1) <= y <= max(y0, y1):
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return (min(xs), max(xs)) if xs else None


def has_outline(lane_shape: str, polygon) -> bool:
    """Rule 2's test: the lane is read as its polygon."""
    return lane_shape != "RECTANGLE" and bool(polygon) and len(polygon) >= 3


def lane_outline(lane_shape: str, polygon: list | None, x: float, y: float, width: float, height: float) -> list:
    """Rule 2 (spec §4): a lane is read as its polygon when it is not a rectangle and has at least 3 points, else as
    its box -- one rule for every reader."""
    if has_outline(lane_shape, polygon):
        return [[float(px), float(py)] for px, py in polygon]
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def outline_of(lane) -> list:
    """Rule 2 on anything with a lane's fields (a model instance, a report row): ``lane_shape``, ``polygon``, ``x``,
    ``y``, ``width``, ``height``."""
    return lane_outline(lane.lane_shape, lane.polygon, lane.x, lane.y, lane.width, lane.height)


def order_corners(points: list) -> list:
    """TL, TR, BR, BL of 4 points by geometry (the two highest are the top, then by x) -- a hand-drawn quadrilateral's
    points come in click order."""
    by_y = sorted(points, key=lambda p: (p[1], p[0]))
    top = sorted(by_y[:2], key=lambda p: p[0])
    bottom = sorted(by_y[2:], key=lambda p: p[0])
    return [top[0], top[1], bottom[1], bottom[0]]


def outer_bbox(polygon: list) -> tuple:
    """(x, y, width, height) of the polygon, rounded outward: the box always contains the polygon."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    x0, y0 = math.floor(min(xs)), math.floor(min(ys))
    return x0, y0, math.ceil(max(xs)) - x0, math.ceil(max(ys)) - y0


def map_polygon_to_box(polygon: list, old_box: tuple, new_box: tuple) -> list:
    """The polygon moved and scaled from ``old_box`` onto ``new_box``, axis by axis (affine: a parallelogram stays one)."""
    ox, oy, ow, oh = old_box
    nx, ny, nw, nh = new_box
    sx = nw / ow if ow else 1.0
    sy = nh / oh if oh else 1.0
    return [[nx + (px - ox) * sx, ny + (py - oy) * sy] for px, py in polygon]


def extend_quad(polygon: list, y_top: float, y_bottom: float) -> list:
    """A 4-point lane's sides extended or cut, as lines, to ``y_top`` and ``y_bottom``: its slope is kept."""
    tl, tr, br, bl = order_corners(polygon)

    def at(a, b, y):
        if b[1] == a[1]:
            return a[0]
        return a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])

    return [
        [at(tl, bl, y_top), y_top],
        [at(tr, br, y_top), y_top],
        [at(tr, br, y_bottom), y_bottom],
        [at(tl, bl, y_bottom), y_bottom],
    ]


def normalize_lane_write(payload: dict, stored: dict | None, image_size: tuple | None) -> dict:
    """Rule 1 (spec §4): the payload with the geometry the server stores.

    ``stored`` is the lane as it is (``lane_shape``, ``polygon``, x/y/width/height), None on a create; ``image_size``
    is (width, height) or None. A non-rectangle lane's box becomes its polygon's outer box; a box-only change maps the
    stored polygon onto the new box; a polygon equal to the stored one is not rewritten, so re-sending an unchanged
    lane never wipes its densitometry (D1). Raises GeometryRefused.
    """
    out = dict(payload)
    stored = stored or {}
    shape = payload.get("lane_shape", stored.get("lane_shape", "RECTANGLE"))
    if shape == "RECTANGLE":
        return out
    polygon = payload.get("polygon")
    if polygon is None and stored.get("polygon") and any(k in payload for k in BOX_KEYS):
        old = tuple(stored[k] for k in BOX_KEYS)
        new = tuple(payload.get(k, stored[k]) for k in BOX_KEYS)
        polygon = map_polygon_to_box(stored["polygon"], old, new)
    if polygon is None:
        return out
    if not isinstance(polygon, list) or not all(
        isinstance(p, (list, tuple)) and len(p) == 2 and all(_is_finite(v) for v in p) for p in polygon
    ):
        raise GeometryRefused("the polygon must be a list of [x, y] numbers")
    if stored.get("polygon") is not None and polygon == stored.get("polygon") and shape == stored.get("lane_shape"):
        for key in (*BOX_KEYS, "polygon"):
            out.pop(key, None)
        return out
    points = [[round(float(px)), round(float(py))] for px, py in polygon]
    if len(points) < 3:
        raise GeometryRefused("a polygon lane needs at least 3 points")
    if image_size and all(image_size):
        width, height = image_size
        if any(px < -1 or py < -1 or px > width + 1 or py > height + 1 for px, py in points):
            raise GeometryRefused(f"the polygon leaves the {width}x{height} image")
        points = [[min(max(px, 0), width), min(max(py, 0), height)] for px, py in points]
    if len(points) == 4 and shape == "QUADRILATERAL":
        points = order_corners(points)
    out["polygon"] = points
    out["x"], out["y"], out["width"], out["height"] = outer_bbox(points)
    return out


def _is_finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
