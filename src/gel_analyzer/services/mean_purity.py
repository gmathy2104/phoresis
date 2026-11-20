"""A gel's mean purity: one definition for every page, report and export that shows one.

The mean of the SAMPLE lanes' purity -- the lanes whose purity is their sample's measurement. A
CONTROL, a ladder or a standard runs beside the samples: its POI share is not a sample's
measurement (``signals.lane_publishes_purity``, owner 2026-10-05). A lane counts with the purity it
publishes (``signals.published_purity``): a lane whose POI band carries no signal has none and is
left out, never averaged as 0 %. A gel that does not measure purity (a western blot,
``signals.image_measures_purity``) has no mean purity. The label says what the mean averages
(:attr:`MeanPurity.lanes_text`).

Found 2026-10-13: one gel read 53.2 % on its analysis page (sample lanes) and 56.1 % in its
report and on the comparison page (control lanes included). The comparison averages the lanes put
side by side in the browser: each lane row says whether this rule counts it
(``analysis_detail.payload_row``, ``in_mean_purity``) and the JS only does the arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from gel_analyzer.models import Lane
from gel_analyzer.signals import image_measures_purity


def lane_in_mean_purity(lane_type: str) -> bool:
    """True for a lane a mean purity averages: a SAMPLE lane."""
    return lane_type == Lane.LaneType.SAMPLE


@dataclass(frozen=True)
class MeanPurity:
    """A mean purity and the lanes it averages."""

    value: float | None  # in %; None when no sample lane has a purity, or the gel measures none
    counted: int  # the sample lanes with a purity: the lanes averaged
    sample_lanes: int

    @property
    def lanes_text(self) -> str:
        """What the mean averages: "5 of 7 sample lanes", or "No sample lane"."""
        if not self.sample_lanes:
            return "No sample lane"
        return f"{self.counted} of {self.sample_lanes} sample lanes"


def mean_purity(gel_image, lanes: Iterable[tuple[str, float | None]]) -> MeanPurity:
    """The mean purity of a gel (module docstring).

    ``lanes``: ``(lane_type, purity)`` for each lane of the gel, ``purity`` the one the lane
    publishes (``signals.published_purity`` of its summary; None when it has none). Pass every
    lane: the lanes the rule leaves out are left out here, not by the caller.
    """
    sample = [purity for lane_type, purity in lanes if lane_in_mean_purity(lane_type)]
    if not image_measures_purity(gel_image):
        return MeanPurity(None, 0, len(sample))
    purities = [purity for purity in sample if purity is not None]
    return MeanPurity(sum(purities) / len(purities) if purities else None, len(purities), len(sample))
