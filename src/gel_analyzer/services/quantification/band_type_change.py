"""A band's type and its calibration point change together: the one rule for every write of ``Band.band_type``.

A CALIBRATION band is a point of the quantification curve and carries a ``ProteinQuantCalibrationPoint`` (the loaded
amount and its unit). A band typed CALIBRATION needs that point, given with the write or already stored; a band typed
anything else loses it. Writers: the v1 band PATCH (``api/serializers.py``) and the editor's band endpoints
(``views/api.py``: create, PUT, split). The v1 PATCH evaluates the band's resulting type on every write; the editor's
endpoints when the request writes ``band_type``, so a drag of a legacy CALIBRATION band with no point still saves.

The editor's PUT once wrote the type through a setattr loop (until 2026-10-13): a band typed POI kept its point, which
``guard_lane_type_change`` still counted (a "Discard calibration points?" for a point no band showed) and which came
back into the fit if the band was typed CALIBRATION again; a band typed CALIBRATION was stored with no point at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gel_analyzer.models import Band, Lane

MISSING_POINT = "band_type=CALIBRATION requires a quant_point with load_amount and load_unit"


class BandTypeRefused(Exception):
    """A band_type write the rule refuses. The message is the v1 PATCH's own 400."""


def check_band_type(band: Band | None, band_type, quant_point: dict | None = None, lane: Lane | None = None) -> None:
    """Before ``band`` (as stored; None for a new band) takes ``band_type``. CALIBRATION needs a point, ``quant_point``
    or the stored one, and a given point's unit is the active calibration's. Raises BandTypeRefused."""
    from gel_analyzer.models import Band, ProteinQuantCalibration, ProteinQuantCalibrationPoint

    if band_type != Band.BandType.CALIBRATION:
        return
    if quant_point is None:
        if band is None or not ProteinQuantCalibrationPoint.objects.filter(band=band).exists():
            raise BandTypeRefused(MISSING_POINT)
        return
    lane = lane or (band.lane if band is not None else None)
    if lane is None:
        return
    active = ProteinQuantCalibration.objects.filter(analysis=lane.analysis, is_active=True).first()
    if active and quant_point.get("load_unit") and quant_point["load_unit"] != active.unit:
        raise BandTypeRefused(
            f"Unit {quant_point['load_unit']} differs from the active calibration's unit {active.unit}"
        )


def apply_band_type(band: Band, quant_point: dict | None = None) -> None:
    """After ``band`` is saved with its type, inside the writer's transaction. Any type but CALIBRATION deletes the
    band's point. CALIBRATION: the lane follows (a SAMPLE, LADDER, EMPTY or DOT lane becomes CALIBRATION: the user's
    intent is plain, a two-step would only be in the way; a CONTROL lane stays, its band a control point), then a
    given ``quant_point`` is stored, its role read from the lane."""
    from gel_analyzer.models import Band, Lane, ProteinQuantCalibrationPoint

    if band.band_type != Band.BandType.CALIBRATION:
        ProteinQuantCalibrationPoint.objects.filter(band=band).delete()
        return
    lane = band.lane
    if lane.lane_type not in (Lane.LaneType.CALIBRATION, Lane.LaneType.CONTROL):
        lane.lane_type = Lane.LaneType.CALIBRATION
        lane.save(update_fields=["lane_type"])
    if quant_point is None:
        return
    role = (
        ProteinQuantCalibrationPoint.ROLE_CONTROL
        if lane.lane_type == Lane.LaneType.CONTROL
        else ProteinQuantCalibrationPoint.ROLE_CALIBRATION
    )
    ProteinQuantCalibrationPoint.objects.update_or_create(
        band=band,
        defaults={
            "load_amount": quant_point["load_amount"],
            "load_unit": quant_point["load_unit"],
            "is_excluded_from_fit": quant_point.get("is_excluded_from_fit", False),
            "role": role,
        },
    )
