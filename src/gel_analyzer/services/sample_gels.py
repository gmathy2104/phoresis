"""A lane on its whole gel, as the lane-strip components draw it.

One entry per lane: the whole gel's lane geometry, the lane's bands, stored profile and purity, and
the kDa ticks of the nearest ladder calibration. Read-only. Every lane is read by its outline
(``shape.outline_of``): a tilted lane's box takes in its neighbours.

Ported from ds-hub-django, where this module (hence its name) also lists the gels a Process
Development sample is loaded on and the state of the value each lane published there. Phoresis
keeps :func:`lane_strip_entries`, which needs no sample: every entry's readout state is "none".
"""

from django.urls import reverse
from django.utils import timezone

from gel_analyzer.models import Band, DensitometryResult, LadderCalibration, Lane, LaneDensitometrySummary
from gel_analyzer.services.lane_geometry.shape import outline_of, span_at
from gel_analyzer.signals import lane_measures_purity, published_purity


def _gel_context(analysis_ids):
    """Per analysis: its lanes in drawing order, its ladder calibrations, its calibrated ladder bands."""
    gel_lanes = {}
    for lane in Lane.objects.filter(analysis_id__in=analysis_ids).order_by("lane_number", "x"):
        gel_lanes.setdefault(lane.analysis_id, []).append(lane)
    calibrations = {}
    for calibration in LadderCalibration.objects.filter(
        analysis_id__in=analysis_ids, ladder_lane__isnull=False, ladder_x_position__gt=0
    ):
        calibrations.setdefault(calibration.analysis_id, []).append(calibration)
    ladder_bands = {}
    for band in Band.objects.filter(
        lane__analysis_id__in=analysis_ids,
        lane__lane_type=Lane.LaneType.LADDER,
        band_type=Band.BandType.MW_REFERENCE,
        estimated_mw_kda__isnull=False,
    ).select_related("lane"):
        ladder_bands.setdefault(band.lane.analysis_id, []).append(band)
    return gel_lanes, calibrations, ladder_bands


def lane_strip_entries(lanes) -> dict:
    """``{lane pk: entry}`` -- the LaneStrips entry of ANY lane (no sample needed), for the gel comparison.

    The PD sample comparison's entry (:func:`_entry`: the lane on its whole gel, its bands, its kDa ticks)
    with no Process Development readout (``state: "none"``): the comparison writes its own readout under each
    strip. ``lanes`` come with ``analysis__gel_image__assay``, ``densitometry_summary`` and their bands (with
    ``densitometry``) loaded; the whole-gel lanes, calibrations and ladder bands are batched here (3 queries).
    """
    lanes = list(lanes)
    if not lanes:
        return {}
    gel_lanes, calibrations, ladder_bands = _gel_context({lane.analysis_id for lane in lanes})
    none = {
        "state": "none",
        "analysis_type_id": None,
        "analysis_type_name": "",
        "values": [],
        "held_by_lane_number": None,
        "held_by_analysis_id": None,
        "held_by_analysis_name": "",
    }
    return {
        lane.pk: _entry(
            lane,
            lane_measures_purity(lane),
            gel_lanes.get(lane.analysis_id, []),
            calibrations.get(lane.analysis_id, []),
            ladder_bands.get(lane.analysis_id, []),
            dict(none),
        )
        for lane in lanes
    }


def _entry(lane, purity_lane, gel_lanes, calibrations, ladder_bands, readout) -> dict:
    analysis = lane.analysis
    image = analysis.gel_image
    summary = _summary(lane)
    bands = []
    for band in lane.bands.all():
        densitometry = _densitometry(band)
        bands.append(
            {
                "id": str(band.pk),
                "band_type": band.band_type,
                "position_y": band.position_y,
                "bbox": band.bbox,
                "estimated_mw_kda": band.estimated_mw_kda,
                "relative_percent_lane": densitometry.relative_percent_lane if densitometry is not None else None,
            }
        )
    profile = None
    if summary is not None and summary.profile_data:
        ys = summary.profile_data.get("y_positions") or []
        values = summary.profile_data.get("intensities") or []
        if ys and len(ys) == len(values):
            profile = {"y": ys, "intensity": values}
    # The purity follows published_purity, the same rule as the official row and the export: a POI
    # share above zero, else no number.
    purity = published_purity(summary) if purity_lane and summary is not None else None
    return {
        "lane_id": lane.pk,
        "lane_number": lane.lane_number,
        "measures_purity": purity_lane,
        "analysis": {
            "id": str(analysis.pk),
            "name": analysis.name or "",
            "status": analysis.get_status_display(),
            "created": timezone.localtime(analysis.created_at).date().isoformat(),
            "url": reverse("gel_analyzer:analysis_detail", kwargs={"pk": analysis.pk}),
            "densitometry_url": reverse("gel_analyzer:analysis_densitometry", kwargs={"pk": analysis.pk}),
        },
        "gel_type": image.get_gel_type_display(),
        "assay": {"name": image.assay.name, "readout": image.assay.readout} if image.assay_id else None,
        # Lane coordinates are in display-file pixels (GelImage.width/height); the proxy's fallback,
        # original_file, can be a TIFF no browser draws -- so no display file, no image.
        "image": {
            "url": reverse("gel_analyzer:api_image_proxy", kwargs={"pk": image.pk}) if image.has_display_file else None,
            "width": image.width,
            "height": image.height,
        },
        # The lane as drawn (Rule 2, gel_analyzer/CLAUDE.md): the browser reads it through
        # LaneGeometry.outlineOfPayload, never by its box.
        "lanes": [
            {
                "id": other.pk,
                "lane_number": other.lane_number,
                "lane_type": other.lane_type,
                "outline": outline_of(other),
            }
            for other in gel_lanes
        ],
        "bands": bands,
        "profile": profile,
        "purity": purity,
        "band_count": summary.band_count if summary is not None else len(bands),
        "poi_band_count": (
            summary.poi_band_count if summary is not None else sum(1 for b in bands if b["band_type"] == "POI")
        ),
        "mw_ticks": _mw_ticks(lane, calibrations, ladder_bands),
        "readout": readout,
    }


def _mid_x(lane) -> float:
    """The lane's centre at mid-height, read by its outline (Rule 2): a tilted lane's box centre is the
    axis only under a straight fan."""
    outline = outline_of(lane)
    ys = [y for _, y in outline]
    span = span_at(outline, (min(ys) + max(ys)) / 2)
    if span is None:
        xs = [x for x, _ in outline]
        return (min(xs) + max(xs)) / 2
    return (span[0] + span[1]) / 2


def _mw_ticks(lane, calibrations, ladder_bands) -> list[dict]:
    """kDa ticks in image pixels: the calibration whose ladder is nearest the lane, else the nearest
    ladder lane's MW_REFERENCE bands, else none (western blots often have no calibration)."""
    centre = _mid_x(lane)
    if calibrations:
        calibration = min(calibrations, key=lambda c: abs(c.ladder_x_position - centre))
        ticks = [
            {"mw_kda": match.get("mw_kda"), "y": match.get("position_y")}
            for match in calibration.band_matches or []
            if match.get("mw_kda") and match.get("position_y") is not None
        ]
        if ticks:
            return sorted(ticks, key=lambda tick: tick["y"])
    if ladder_bands:
        by_lane = {}
        for band in ladder_bands:
            by_lane.setdefault(band.lane_id, []).append(band)
        nearest = min(by_lane.values(), key=lambda bands: abs(_mid_x(bands[0].lane) - centre))
        return sorted(({"mw_kda": b.estimated_mw_kda, "y": b.position_y} for b in nearest), key=lambda t: t["y"])
    return []


def _summary(lane):
    try:
        return lane.densitometry_summary
    except LaneDensitometrySummary.DoesNotExist:
        return None


def _densitometry(band):
    try:
        return band.densitometry
    except DensitometryResult.DoesNotExist:
        return None
