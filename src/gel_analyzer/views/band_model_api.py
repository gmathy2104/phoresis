"""JSON endpoints of the band model the annotation editor runs in the browser, after the lane model.

The browser runs the model (WebGPU, CPU fallback: the server has no GPU -- Grégory 2026-10-09); the server says which
model to run and turns its boxes into the bands of each saved lane (``services/band_detection/yolo_bands.py``).

GET  api/analyses/<uuid>/band-model/           the model to run (URL, sha256, settings) and the gel inside its page
POST api/analyses/<uuid>/band-model/preview/   the model's boxes -> the bands of each lane; nothing is written
POST api/analyses/<uuid>/band-model/save/      the same body -> the bands are WRITTEN, as the classical detection does
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.templatetags.static import static
from django.views.decorators.http import require_http_methods

from gel_analyzer.access import user_can_write_gel_analyzer
from gel_analyzer.forms import band_to_dict
from gel_analyzer.models import Band, GelAnalysis
from gel_analyzer.services.analysis_status import AnalysisIsFinal, refuse_if_final
from gel_analyzer.services.band_detection.yolo_bands import (
    BoxesRefused,
    band_type_for,
    bands_from_boxes,
    gel_window_of,
    parse_boxes,
)
from gel_analyzer.services.band_model import BandModelUnavailable, verified_band_model
from gel_analyzer.views.api import json_error, parse_json_body
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

MODEL_UNAVAILABLE = (
    "The band model is not available on this server: its file does not match its configuration. "
    "Tell an administrator (system check gel_analyzer.E001)."
)
NO_WRITE_ACCESS = "You need write access to gel analyses to save bands."
NOT_EDITABLE = "Analysis is not editable"

# What a new detection replaces on a lane: every auto-detected band, whichever detector wrote it; MANUAL bands stay
# (the rule of the classical Hybrid detection, whose endpoints were removed on 2026-10-13).
AUTO_DETECTED_SOURCES = (
    Band.DetectionSource.HYBRID,
    Band.DetectionSource.AUTO,
    Band.DetectionSource.CV2_VISION,
    Band.DetectionSource.PROFILE,
    Band.DetectionSource.YOLO,
    Band.DetectionSource.SAM,
)


def _model_or_refusal():
    """(config, None) or (None, the 503 response): a browser never gets a file the server cannot vouch for."""
    try:
        return verified_band_model(), None
    except BandModelUnavailable as exc:
        logger.error(f"Band model refused: {exc}")
        return None, json_error(MODEL_UNAVAILABLE, 503)


@login_required
@require_http_methods(["GET"])
def api_band_model_context(request, pk):
    """GET: what the browser needs to run the band model on this analysis's gel."""
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)
    config, refusal = _model_or_refusal()
    if refusal:
        return refusal
    gel = analysis.gel_image
    return JsonResponse(
        {
            "success": True,
            "model": {
                "name": config["name"],
                "url": static(config["static_path"]),
                "sha256": config["sha256"],
                "source_sha256": config["source_sha256"],
                "class_names": config["class_names"],
                "imgsz": config["imgsz"],
                "confidence": config["confidence"],
                "min_confidence": config["min_confidence"],
                "iou": config["iou"],
                "max_det": config["max_det"],
            },
            # The model runs on the gel cut out of a scanned page, at the scale it learned bands at; the browser
            # shifts its boxes back by the window's corner before posting them.
            "image": {"width": gel.width, "height": gel.height, "gel_window": gel_window_of(gel)},
            "editable": analysis.is_editable,
            # The page greys "Save all" for a reader; the save refuses one anyway.
            "can_write": user_can_write_gel_analyzer(request.user),
        }
    )


@dataclass
class _Request:
    """A preview or save body, checked against the configured model, this gel and this analysis's lanes."""

    config: dict
    confidence: float
    lanes: list
    boxes: list


def _parse(request, analysis):
    """(_Request, None) or (None, the refusal): the preview and the save refuse exactly the same bodies."""
    data = parse_json_body(request)
    if not isinstance(data, dict):
        return None, json_error("Invalid JSON in request body")
    config, refusal = _model_or_refusal()
    if refusal:
        return None, refusal

    if data.get("model_sha256") != config["sha256"]:
        return None, json_error(
            "This page ran another band model than the server's "
            f"({str(data.get('model_sha256'))[:12]}… instead of {config['sha256'][:12]}…). Reload the page.",
            409,
        )
    gel = analysis.gel_image
    posted = data.get("image") or {}
    if not gel.width or not gel.height:
        return None, json_error("This gel has no recorded image size; its bands cannot be placed.")
    if posted.get("width") != gel.width or posted.get("height") != gel.height:
        return None, json_error(
            f"The boxes were found on a {posted.get('width')}x{posted.get('height')} image, "
            f"this gel's is {gel.width}x{gel.height}. Reload the page."
        )
    confidence = data.get("confidence", config["confidence"])
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, json_error("confidence must be a number")
    if not config["min_confidence"] <= confidence < 1:
        return None, json_error(f"confidence must be between {config['min_confidence']} and 1")

    lanes = list(analysis.lanes.all().order_by("lane_number"))
    lane_ids = data.get("lane_ids")
    if lane_ids is not None:
        if not isinstance(lane_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in lane_ids):
            return None, json_error("lane_ids must be a list of lane ids")
        unknown = set(lane_ids) - {lane.pk for lane in lanes}
        if unknown:
            return None, json_error(f"Lanes {sorted(unknown)} are not lanes of this analysis")
        lanes = [lane for lane in lanes if lane.pk in set(lane_ids)]
    if not lanes:
        return None, json_error("Create lanes first: bands are placed in the saved lanes.")
    try:
        boxes = parse_boxes(data.get("boxes"), gel.width, gel.height, config["max_det"])
    except BoxesRefused as exc:
        return None, json_error(f"Invalid boxes: {exc}")
    return _Request(config, float(confidence), lanes, boxes), None


def _bands(analysis, parsed: _Request):
    from gel_analyzer.services.file_handler import GelFileHandler  # noqa: PLC0415 -- as the other detection views

    image = GelFileHandler.load_image_as_array(analysis.gel_image)
    return bands_from_boxes(parsed.boxes, parsed.lanes, image, parsed.confidence, parsed.config["iou"])


def _counters(result) -> dict:
    return {
        "band_count": result.band_count,
        "below_threshold": result.below_threshold,
        "empty": result.empty,
        "outside_lanes": result.outside_lanes,
        "superposed": result.superposed,
    }


@login_required
@require_http_methods(["POST"])
def api_band_model_preview(request, pk):
    """POST {model_sha256, image: {width, height}, boxes: [[x1, y1, x2, y2, score]...], confidence?, lane_ids?}:
    the bands each lane would get, in the classical detection's shape. Writes nothing."""
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)
    parsed, refusal = _parse(request, analysis)
    if refusal:
        return refusal
    result = _bands(analysis, parsed)
    return JsonResponse(
        {
            "success": True,
            "model": {"name": parsed.config["name"], "sha256": parsed.config["sha256"]},
            "confidence": parsed.confidence,
            **_counters(result),
            "lanes": [
                {
                    "lane_id": entry.lane.pk,
                    "lane_number": entry.lane.lane_number,
                    "lane_type": entry.lane.lane_type,
                    "band_type": band_type_for(entry.lane),
                    "band_count": len(entry.bands),
                    # score = the unrounded confidence: the page's slider filters on it exactly as the save will.
                    "bands": [{**band.to_dict(), "score": band.confidence} for band in entry.bands],
                }
                for entry in result.lanes
            ],
        }
    )


class _NotEditable(Exception):
    pass


@login_required
@require_http_methods(["POST"])
def api_band_model_save(request, pk):
    """POST, the preview's body (with the chosen confidence and lanes): the bands are WRITTEN, the way the classical
    Hybrid detection wrote them: on each lane every auto-detected band is replaced
    and the hand-drawn (MANUAL) ones stay; one ``Band.objects.create`` per band, so the densitometry of each touched
    lane goes stale and simple-history records each row, through the same signals as any band edit.

    Refused (nothing written) for a reader, an approved analysis (final), an analysis not editable, another model."""
    analysis = get_object_or_404(GelAnalysis.objects.select_related("gel_image"), pk=pk)
    if not user_can_write_gel_analyzer(request.user):
        return json_error(NO_WRITE_ACCESS, 403)
    try:
        refuse_if_final(analysis.pk)
    except AnalysisIsFinal as exc:
        return json_error(str(exc), 403)
    if not analysis.is_editable:
        return json_error(NOT_EDITABLE, 403)
    parsed, refusal = _parse(request, analysis)
    if refusal:
        return refusal
    result = _bands(analysis, parsed)  # the image read and the intensities, outside the transaction

    config = parsed.config
    metadata = {
        "detector": "band_model",
        "model": config["name"],
        "model_sha256": config["sha256"],
        "model_source_sha256": config["source_sha256"],
        "confidence_threshold": parsed.confidence,
    }
    deleted = created = 0
    try:
        with transaction.atomic():
            # Again under the analysis row lock: it can be approved, or leave the editable statuses, between the
            # checks above and this write (the densitometry writer locks the same way).
            refuse_if_final(analysis.pk, lock=True)
            if not GelAnalysis.objects.only("status").get(pk=analysis.pk).is_editable:
                raise _NotEditable()
            for entry in result.lanes:
                _, per_model = Band.objects.filter(lane=entry.lane, detection_source__in=AUTO_DETECTED_SOURCES).delete()
                deleted += per_model.get(Band._meta.label, 0)
                band_type = band_type_for(entry.lane)
                for number, detected in enumerate(entry.bands, 1):
                    Band.objects.create(
                        lane=entry.lane,
                        band_number=number,
                        position_y=detected.position_y,
                        bbox_x=detected.bbox_x,
                        bbox_y=detected.bbox_y,
                        bbox_width=detected.bbox_width,
                        bbox_height=detected.bbox_height,
                        polygon=detected.polygon,
                        confidence=detected.confidence,
                        detection_source=Band.DetectionSource.YOLO,
                        band_type=band_type,
                        intensity_raw=detected.intensity_raw,
                        intensity_peak=detected.intensity_peak,
                        area_pixels=detected.area_pixels,
                        metadata=dict(metadata),
                        created_by=request.user,
                    )
                    created += 1
            analysis.update_counts()
    except AnalysisIsFinal as exc:
        return json_error(str(exc), 403)
    except _NotEditable:
        return json_error(NOT_EDITABLE, 403)

    logger.info(
        f"Band model bands saved: {created} created, {deleted} auto-detected replaced",
        user=request.user.username,
        analysis_id=str(analysis.pk),
        lanes=len(result.lanes),
        model_sha256=config["sha256"][:12],
    )
    return JsonResponse(
        {
            "success": True,
            "created_count": created,
            "deleted_count": deleted,
            "confidence": parsed.confidence,
            **_counters(result),
            # Every band of each saved lane, hand-drawn ones included: the page re-renders the lanes from this.
            "lanes": [
                {
                    "lane_id": entry.lane.pk,
                    "bands": [band_to_dict(band) for band in entry.lane.bands.order_by("position_y")],
                }
                for entry in result.lanes
            ],
        }
    )
