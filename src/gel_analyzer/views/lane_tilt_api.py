"""The tilt of the lanes the lane model found, for the review's *Follow the lanes* (spec 2026-10-10 §10).

POST api/analyses/<uuid>/lanes/tilt/   {token, boxes: [{index, box: [x, y, w, h], mask_slope}]} -> each lane's axis

The browser sends each detection's box and its own mask slope (the lane worker's fit); the server keeps the slope
unless a reliable measurement on the display file contradicts it (``tilt_lanes``' ``mask_guarded``, the rule the
bench validated, §9) and answers each lane's axis. Computes only: nothing is written.
"""

from __future__ import annotations

import math

import numpy as np

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from gel_analyzer.models import GelAnalysis
from gel_analyzer.services.lane_geometry.tilt import APP_MIN_DRIFT_PX, APP_SLOPE_RULE, tilt_lanes
from gel_analyzer.views.api import json_error, parse_json_body
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

MAX_BOXES = 200


class _Refused(ValueError):
    pass


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse(data, width: int, height: int) -> tuple[str, list, dict]:
    """(token, [(index, box)], {index: mask_slope}) or _Refused with what is wrong."""
    if not isinstance(data, dict):
        raise _Refused("the body must be a JSON object")
    token = data.get("token")
    if not isinstance(token, str) or not token or len(token) > 64:
        raise _Refused("token must be a non-empty string of at most 64 characters")
    raw = data.get("boxes")
    if not isinstance(raw, list) or not raw:
        raise _Refused("boxes must be a non-empty list")
    if len(raw) > MAX_BOXES:
        raise _Refused(f"{len(raw)} boxes, more than {MAX_BOXES}")
    boxes, slopes, seen = [], {}, set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _Refused(f"box {position} is not an object")
        index, box, slope = item.get("index"), item.get("box"), item.get("mask_slope")
        if not isinstance(index, int) or isinstance(index, bool) or index in seen:
            raise _Refused(f"box {position}: index must be an integer, once")
        seen.add(index)
        if not isinstance(box, list) or len(box) != 4 or not all(_finite(v) for v in box):
            raise _Refused(f"box {position}: box must be [x, y, width, height] of finite numbers")
        x, y, w, h = box
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width + 1 or y + h > height + 1:
            raise _Refused(f"box {position} {box} is not inside the {width}x{height} image")
        if slope is not None and not _finite(slope):
            raise _Refused(f"box {position}: mask_slope must be null or a finite number")
        boxes.append((index, (float(x), float(y), float(w), float(h))))
        slopes[index] = None if slope is None else float(slope)
    return token, boxes, slopes


def _display_grey(gel_image):
    """The display file as 8-bit grey (the pixels the lane model saw, spec D10), or None."""
    import cv2  # noqa: PLC0415 -- as yolo_bands.gel_window_of

    if not gel_image.display_file:
        return None
    with gel_image.display_file.open("rb") as handle:
        return cv2.imdecode(np.frombuffer(handle.read(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


@login_required
@require_http_methods(["POST"])
def api_lane_tilt(request, pk):
    """POST {token, boxes: [{index, box, mask_slope}]}: each lane's axis (x at y_ref, slope), width and source."""
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)
    gel = analysis.gel_image
    if not gel.width or not gel.height:
        return json_error("This gel has no recorded image size; its lanes cannot be measured.")
    try:
        token, boxes, slopes = _parse(parse_json_body(request), gel.width, gel.height)
    except _Refused as exc:
        return json_error(f"Invalid lanes: {exc}")
    gray = _display_grey(gel)
    if gray is None:
        return json_error("This gel has no display image to measure its lanes on.")
    result = tilt_lanes(gray, boxes, slope_rule=APP_SLOPE_RULE, min_drift_px=APP_MIN_DRIFT_PX, mask_slopes=slopes)
    return JsonResponse(
        {
            "success": True,
            "token": token,
            "y_ref": result.y_ref,
            "lanes": [
                {
                    "index": lane.index,
                    "x_ref": lane.x_ref,
                    "slope": lane.slope,
                    "width": lane.width,
                    "source": lane.source,
                }
                for lane in result.lanes
            ],
        }
    )
