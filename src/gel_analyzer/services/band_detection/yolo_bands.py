"""Bands from the browser-run band model, built the way the classical detection builds them.

The annotation editor runs ``settings.GEL_ANALYZER_BAND_MODEL`` in the browser (lanes first, with the lane model;
then this model ONCE on the whole gel -- Grégory 2026-10-09) and posts the model's boxes in image pixels. Everything
after the boxes happens here, once, for the preview and for the save alike:

* a box belongs to the saved lane that holds its centre (where lanes overlap, the one whose centre is nearest); a
  box in no lane is dropped and counted;
* inside a lane a band spans the lane's width, from the box's top to its bottom clipped to the lane -- the shape the
  CV2 path writes, and what the densitometry reads: ``position_y`` and the top and bottom of the band's box on the
  lane's profile (``services/densitometry/peak_integrator.py``);
* two boxes of one lane whose top-bottom intervals overlap at 1-D IoU >= the model's NMS ``iou`` are one band (two
  boxes side by side at the same height): the most confident stays. Measured on the 46 REVIEWED gels of 2026-10-06:
  14 superposed bands fewer for 3 true bands lost; kept because a superposed pair is integrated twice;
* intensities as the CV2 path computes them: the lane cut out of ``GelFileHandler.load_image_as_array``, brought to
  8 bits and CLAHE'd with the hybrid's default parameters, summed over the band's rows.

Inconsistent input is refused with what is wrong (:class:`BoxesRefused`), never repaired.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from phoresis_core.logging_config import get_logger

from ..lane_geometry.shape import outline_of, span_at
from .models import BandDetectionSource, DetectedBand

logger = get_logger(__name__)


class BoxesRefused(ValueError):
    """The posted boxes cannot be the band model's output on this image."""


@dataclass(frozen=True)
class ModelBox:
    """One box of the band model, in the gel image's pixels."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


@dataclass
class LaneBands:
    lane: object  # gel_analyzer.models.Lane
    bands: list[DetectedBand] = field(default_factory=list)


@dataclass
class BandsFromModel:
    lanes: list[LaneBands]
    below_threshold: int = 0
    empty: int = 0
    outside_lanes: int = 0
    superposed: int = 0

    @property
    def band_count(self) -> int:
        return sum(len(entry.bands) for entry in self.lanes)


def parse_boxes(raw, width: int, height: int, max_det: int) -> list[ModelBox]:
    """``[[x1, y1, x2, y2, score], ...]`` checked against the image the browser was given; refused, never clipped."""
    if not isinstance(raw, list):
        raise BoxesRefused("boxes must be a list of [x1, y1, x2, y2, score]")
    if len(raw) > max_det:
        raise BoxesRefused(f"{len(raw)} boxes, more than the model's max_det {max_det}")
    boxes = []
    for index, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) != 5:
            raise BoxesRefused(f"box {index} is not [x1, y1, x2, y2, score]")
        if not all(_is_finite_number(v) for v in item):
            raise BoxesRefused(f"box {index} holds a value that is not a finite number")
        x1, y1, x2, y2, score = (float(v) for v in item)
        # <=, not <: ultralytics clips a box to the image and can leave it EMPTY against an edge (y1 == y2 == 0 on a
        # bench gel, 2026-10-09) -- a real output of the model, dropped and counted by bands_from_boxes.
        if not (0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height):
            raise BoxesRefused(f"box {index} {item[:4]} is not inside the {width}x{height} image")
        if not 0 <= score <= 1:
            raise BoxesRefused(f"box {index} has score {score}, outside 0..1")
        boxes.append(ModelBox(x1, y1, x2, y2, score))
    return boxes


def band_type_for(lane) -> str:
    """The classical Hybrid detection's rule: a ladder lane holds MW references,
    any other lane OTHER -- the model knows one class, ``band``; a POI is still marked by hand."""
    from gel_analyzer.models import Band, Lane  # noqa: PLC0415 -- keeps this module importable without the registry

    return Band.BandType.MW_REFERENCE if lane.lane_type == Lane.LaneType.LADDER else Band.BandType.OTHER


def lane_box(lane) -> tuple[int, int, int, int]:
    b = lane.bbox
    return int(b["x"]), int(b["y"]), int(b["width"]), int(b["height"])


def lane_holding(lanes: list, cx: float, cy: float):
    """The lane whose outline holds (cx, cy) on row cy; where lanes overlap, the one whose row centre is nearest.
    None if none. For a rectangle -- or an upright 4-point polygon -- the row's span is the box: today's rule."""
    best, best_distance = None, None
    for lane in lanes:
        span = span_at(outline_of(lane), cy)
        if span and span[0] <= cx <= span[1]:
            distance = abs((span[0] + span[1]) / 2 - cx)
            if best is None or distance < best_distance:
                best, best_distance = lane, distance
    return best


def bands_from_boxes(boxes: list[ModelBox], lanes: list, image: np.ndarray, confidence: float, overlap_iou: float):
    """The bands of each lane, top to bottom, as :class:`BandsFromModel`.

    ``image`` is ``GelFileHandler.load_image_as_array(gel_image)`` (display-space, what the lane boxes refer to).
    """
    from .cv2_detector import CV2BandDetector  # noqa: PLC0415 -- cv2/scipy on demand, as the other detectors
    from .hybrid_params import HybridDetectionParams  # noqa: PLC0415

    result = BandsFromModel(lanes=[LaneBands(lane) for lane in lanes])
    by_lane = {id(entry.lane): entry for entry in result.lanes}
    kept: dict[int, list[tuple[float, float, float]]] = {id(lane): [] for lane in lanes}
    for box in boxes:
        if box.score < confidence:
            result.below_threshold += 1
            continue
        if box.x2 <= box.x1 or box.y2 <= box.y1:
            result.empty += 1
            continue
        lane = lane_holding(lanes, *box.centre)
        if lane is None:
            result.outside_lanes += 1
            continue
        _, y, _, h = lane_box(lane)
        top, bottom = max(box.y1, float(y)), min(box.y2, float(y + h))
        kept[id(lane)].append((top, bottom, box.score))

    cv2_detector = CV2BandDetector(HybridDetectionParams().to_cv2_params())
    for lane in lanes:
        intervals = []
        for top, bottom, score in sorted(kept[id(lane)], key=lambda t: -t[2]):
            if any(_iou_1d((top, bottom), (k[0], k[1])) >= overlap_iou for k in intervals):
                result.superposed += 1
                continue
            intervals.append((top, bottom, score))
        if intervals:
            by_lane[id(lane)].bands = _build(lane, sorted(intervals), image, cv2_detector)
    return result


def _build(lane, intervals, image: np.ndarray, cv2_detector) -> list[DetectedBand]:
    """Lane-wide bands from (top, bottom, score) in image pixels -- CV2BandDetector._build_bands' shape and stats.

    A band is the lane's outline cut at its top and bottom (spec 2026-10-10 §5.1): on a tilted lane a slanted slice
    of the lane, its stats summed over the lane's own span of each row; on a rectangle -- or an upright 4-point
    polygon -- the box-wide rectangle and sums it always was.
    """
    x, y, w, h = lane_box(lane)
    outline = outline_of(lane)
    gray = cv2_detector._normalize_to_uint8(image[y : y + h, x : x + w])  # same 8 bits as the CV2 path
    if cv2_detector.params.clahe_enabled:
        gray = cv2_detector._apply_clahe(gray)
    bands = []
    for top, bottom, score in intervals:
        y_start = max(0, min(h - 1, int(round(top)) - y))
        y_end = max(y_start + 1, min(h, int(round(bottom)) - y))
        mask = np.zeros((y_end - y_start, w), dtype=bool)
        for row in range(y_start, y_end):
            span = span_at(outline, y + row) or (x, x + w)
            mask[row - y_start, max(0, math.floor(span[0]) - x) : min(w, math.ceil(span[1]) - x)] = True
        values = gray[y_start:y_end, :][mask]
        slice_ = [
            [*_span_or_box(outline, y + y_start, x, w), y + y_start],
            [*_span_or_box(outline, y + y_end, x, w), y + y_end],
        ]
        (left_top, right_top, y_top), (left_bottom, right_bottom, y_bottom) = slice_
        polygon = [[left_top, y_top], [right_top, y_top], [right_bottom, y_bottom], [left_bottom, y_bottom]]
        box_left, box_right = min(left_top, left_bottom), max(right_top, right_bottom)
        bands.append(
            DetectedBand(
                position_y=y + (y_start + y_end) // 2,
                bbox_x=box_left,
                bbox_y=y + y_start,
                bbox_width=box_right - box_left,
                bbox_height=y_end - y_start,
                polygon=polygon,
                confidence=float(score),
                detection_source=BandDetectionSource.YOLO,
                intensity_raw=float(np.sum(values)),
                intensity_peak=float(np.max(values)) if values.size else 0.0,
                area_pixels=int(values.size),
            )
        )
    return bands


def _span_or_box(outline: list, row: float, x: int, w: int) -> tuple[int, int]:
    """The outline's integer span on ``row`` (rounded outward), the lane box's when the row misses the outline."""
    span = span_at(outline, row)
    if span is None:
        return x, x + w
    return math.floor(span[0]), math.ceil(span[1])


def gel_window_of(gel_image) -> list[int] | None:
    """[x, y, w, h] of the gel inside a scanned page, or None -- ml_annotator's rule, so the model sees the gel at the
    scale it was trained on. Never a condition for detecting: a failure leaves the whole image to the model."""
    import cv2  # noqa: PLC0415

    from .gel_window import gel_window  # noqa: PLC0415

    # The display file only: lanes and boxes live in its pixels (GelImage.width x height). An original file can be
    # larger (load_image_as_array resizes it), and a window found on it would be in another pixel space.
    if not gel_image.display_file:
        return None
    try:
        with gel_image.display_file.open("rb") as handle:
            grey = cv2.imdecode(np.frombuffer(handle.read(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if grey is None:
            return None
        window = gel_window(grey)
    except Exception:  # noqa: BLE001 -- the whole image goes to the model (docstring)
        logger.exception(f"Gel window detection failed for GelImage {gel_image.pk}; the whole image goes to the model")
        return None
    return None if window is None else [int(v) for v in window]


def _iou_1d(a, b) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
