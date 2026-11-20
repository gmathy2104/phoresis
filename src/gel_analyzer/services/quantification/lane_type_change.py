"""A lane leaving CALIBRATION/CONTROL while its bands hold calibration points: refused, unless forced, then purged.

The one rule for every write of ``Lane.lane_type``: the v1 PATCH (``api/views.py::LaneViewSet.partial_update``), the
editor's lane PUT and its bulk lane update (``views/api.py``). The two editor endpoints once wrote the type without
it, so a client path that skipped the v1 PATCH left ``ProteinQuantCalibrationPoint`` rows on a SAMPLE or LADDER lane
without an error: invisible to the fit (``calibration_point_bands_q`` reads CALIBRATION lanes only), still the lane's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gel_analyzer.models import Lane

# Lane.LaneType values whose bands may hold calibration points (role CALIBRATION or CONTROL).
POINT_HOLDING_LANE_TYPES = ("CALIBRATION", "CONTROL")

REFUSAL_DETAIL = "Lane has calibration points. Pass ?force=true to purge them."


class CalibrationPointsHeld(Exception):
    """A lane write leaves CALIBRATION/CONTROL while calibration points sit on its bands, without ``force``."""

    def __init__(self, lane: Lane, band_ids: list):
        super().__init__(REFUSAL_DETAIL)
        self.lane = lane
        self.band_ids = band_ids

    def payload(self) -> dict:
        """The 409 body. The editor and the lane spreadsheet count ``dependent_band_ids`` in the confirmation they show
        before sending the same write again with ``?force=true``."""
        return {"detail": REFUSAL_DETAIL, "dependent_band_ids": [str(band_id) for band_id in self.band_ids]}


def guard_lane_type_change(lane: Lane, new_type, *, force: bool) -> None:
    """Before ``lane`` (as stored) takes ``new_type``. Leaving CALIBRATION/CONTROL with calibration points on its
    bands raises CalibrationPointsHeld, unless ``force``: then the points are deleted and the lane's CALIBRATION bands
    become OTHER. Called inside the writer's transaction, so a write that fails afterwards purges nothing."""
    from gel_analyzer.models import Band, ProteinQuantCalibrationPoint

    leaves = new_type and lane.lane_type in POINT_HOLDING_LANE_TYPES and new_type not in POINT_HOLDING_LANE_TYPES
    if not leaves:
        return
    points = ProteinQuantCalibrationPoint.objects.filter(band__lane=lane)
    band_ids = list(points.values_list("band_id", flat=True))
    if not band_ids:
        return
    if not force:
        raise CalibrationPointsHeld(lane, band_ids)
    points.delete()
    Band.objects.filter(lane=lane, band_type=Band.BandType.CALIBRATION).update(band_type=Band.BandType.OTHER)
