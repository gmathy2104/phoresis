"""
Saturation: the share of a band's pixels that sit at the end of the image's scale.

A pixel at the end of the scale on the band's side -- the darkest value for dark bands on a light
background, the brightest for bright bands on a dark one -- can go no further: once a band's core
reaches it, loading more protein no longer grows the band's area. Run through this pipeline
(2026-10-13), a POI loaded 2.6x lost 15 % of its area and its lane's purity fell from 79.5 % to
76.6 %. Gel scientists asked for the check.

What is counted: the pixels the lane profile averaged (``IntensityProfile.row_windows``: the central
window of the lane, row by row) on the rows the band is integrated on (``peak_integrator.band_window``).
They are counted on the ORIGINAL file, at its own bit depth, when the caller passes it: the resize to
the display grid interpolates a clipped core with its neighbours, and its Lanczos ringing can clip
pixels that were not. Without it, on the array the profile was read from.

The end of the scale is the scale's own, never guessed from the band: 0 / the dtype maximum for an
unsigned-integer image (8 or 16 bit), the image's minimum / maximum for a float or signed one, which
has no fixed end. The side is the lane's polarity as the profile processor decided it
(``IntensityProfile.was_inverted``: inverted means dark bands). Known blind spot: a sensor that clips
below its file's maximum (12-bit data in a 16-bit file) is not seen on the bright side.

A WARNING ONLY: no area, share, purity or estimate is corrected for it. ``is_saturated`` reads a stored
fraction against ``settings.GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD`` at every read, so a new threshold
applies to the stored results without a re-run; every surface (the pages, the CSV, the gel export)
flags through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from gel_analyzer.services.band_detection.profile_extractor import to_grayscale

if TYPE_CHECKING:
    from gel_analyzer.services.band_detection.models import IntensityProfile


def saturated_pixel_threshold() -> float:
    """The share of saturated pixels above which a band is flagged (``GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD``)."""
    value = float(settings.GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD)
    if not 0.0 <= value < 1.0:
        raise ImproperlyConfigured(f"GEL_ANALYZER_SATURATED_PIXEL_THRESHOLD is a share in [0, 1), not {value!r}")
    return value


def is_saturated(fraction: float | None) -> bool | None:
    """Whether a band is saturated: its share above the threshold. None when it was never measured."""
    if fraction is None:
        return None
    return fraction > saturated_pixel_threshold()


def scale_ends(pixels: np.ndarray) -> tuple[float, float]:
    """(dark end, bright end) of the image's scale: the dtype's for unsigned integers, else the image's own."""
    if pixels.dtype.kind == "u":
        return 0.0, float(np.iinfo(pixels.dtype).max)
    return float(np.nanmin(pixels)), float(np.nanmax(pixels))


@dataclass(frozen=True)
class SaturationProbe:
    """Counts a gel's saturated pixels: built once per run, read for every band."""

    pixels: np.ndarray  # 2-D: the array counted on (the original file when given)
    scale_x: float  # counted columns per profile-grid column
    scale_y: float  # counted rows per profile-grid row
    dark_end: float
    bright_end: float

    @classmethod
    def of(cls, image: np.ndarray, original: np.ndarray | None = None) -> SaturationProbe:
        """For profiles read from ``image``; counted on ``original`` (the file before its resize) when given."""
        grid = to_grayscale(image)
        pixels = grid if original is None else to_grayscale(original)
        grid_h, grid_w = grid.shape[:2]
        h, w = pixels.shape[:2]
        dark_end, bright_end = scale_ends(pixels)
        return cls(pixels, w / grid_w, h / grid_h, dark_end, bright_end)

    def band_fraction(self, profile: IntensityProfile, top: float, bottom: float) -> float | None:
        """The share (0-1) of the pixels of profile rows ``top``..``bottom`` (both included) at the band-side end.

        None when nothing can be counted: a profile without its row windows, or no profile row in the band.
        """
        y_positions = np.asarray(profile.y_positions)
        if len(profile.row_windows) != len(y_positions):
            return None
        end = self.dark_end if profile.was_inverted else self.bright_end
        height, width = self.pixels.shape[:2]
        at_end = counted = 0
        for index in np.flatnonzero((y_positions >= top) & (y_positions <= bottom)):
            y = int(y_positions[index])
            x_start, x_end = profile.row_windows[index]
            row_0, row_1 = _span(y, y + 1, self.scale_y, height)
            col_0, col_1 = _span(x_start, x_end, self.scale_x, width)
            block = self.pixels[row_0:row_1, col_0:col_1]
            at_end += int(np.count_nonzero(block == end))
            counted += block.size
        return at_end / counted if counted else None


def _span(start: int, stop: int, scale: float, limit: int) -> tuple[int, int]:
    """``[start, stop)`` of the profile grid as ``[first, last)`` of the counted array: one pixel at least, inside."""
    first = max(0, min(int(round(start * scale)), limit - 1))
    last = min(max(int(round(stop * scale)), first + 1), limit)
    return first, last
