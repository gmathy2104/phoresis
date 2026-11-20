"""The densitometry's saturation flag, through the run that stores it (services/densitometry/saturation.py).

One gel, three lanes: a POI band whose core the scanner clipped (a quadrilateral lane, the polygon path of the
profile), a POI band that never reaches the end of the scale (a rectangle lane), and a clipped ladder marker. The
run gets the display grid AND the original it was "resized" from: the display's clipped core is lifted off the
scale end (as a resize does), so only a count on the original finds it. Both polarities: dark bands on a stained
gel (end = 0), bright bands on a fluorescent blot (end = the dtype maximum); each clean box holds background pixels
sitting exactly at the OTHER end, so a swapped polarity would flag it.
"""

import numpy as np
import pytest

from gel_analyzer.models import Band, DensitometryResult, Lane
from gel_analyzer.services.analysis_detail import saturated_bands
from gel_analyzer.services.densitometry import DensitometryService
from gel_analyzer.services.densitometry.saturation import saturated_pixel_threshold

BAND_Y = 250  # display rows; the box is BAND_Y - 20 .. BAND_Y + 20
SIGMA = 4.0  # display rows: the profile is exactly 255 again beyond ~15 rows from the centre


def _gel(dark_bands: bool) -> tuple[np.ndarray, np.ndarray]:
    """(display 500x400, original 1000x800) uint8: lanes 2 and 3 clip, lane 1 stays 105 levels off the end."""
    rows = np.arange(1000)[:, None] / 2.0  # original rows in display coordinates
    shape = np.exp(-((rows - BAND_Y) ** 2) / (2 * SIGMA**2))
    depth = np.zeros((1000, 800))
    for x0, x1, amount in ((50, 90, 150.0), (100, 140, 400.0), (150, 190, 400.0)):  # display columns
        depth[:, 2 * x0 : 2 * x1] = (shape * amount)[:, :1]
    original = np.rint(np.clip(255.0 - depth, 0, 255)).astype(np.uint8)
    display = original[::2, ::2].copy()
    display[display == 0] = 1  # the resize lifts the clipped core off the end of the scale
    if dark_bands:
        return display, original
    return 255 - display, 255 - original


def _band(lane, band_type):
    return Band.objects.create(
        lane=lane,
        band_type=band_type,
        position_y=BAND_Y,
        bbox_x=lane.x,
        bbox_y=BAND_Y - 20,
        bbox_width=40,
        bbox_height=40,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("dark_bands", [True, False], ids=["dark_bands", "bright_bands"])
def test_clipped_band_is_flagged_on_the_original_file_and_a_clean_one_is_not(
    dark_bands, gel_analysis, sample_lane, ladder_lane, test_user
):
    clipped_lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=3,
        lane_type=Lane.LaneType.SAMPLE,
        x=150,
        y=10,
        width=40,
        height=480,
        lane_shape=Lane.LaneShape.QUADRILATERAL,
        polygon=[[150, 10], [190, 10], [190, 490], [150, 490]],
    )
    clean = _band(sample_lane, Band.BandType.POI)
    marker = _band(ladder_lane, Band.BandType.MW_REFERENCE)
    clipped = _band(clipped_lane, Band.BandType.POI)
    display, original = _gel(dark_bands)

    result = DensitometryService().analyze_and_save(gel_analysis, display, test_user, original_image=original)
    assert result.success, result.error_message

    stored = {row.band_id: row for row in DensitometryResult.objects.filter(band__lane__analysis=gel_analysis)}
    assert stored[clipped.pk].saturated is True
    assert saturated_pixel_threshold() < stored[clipped.pk].saturated_pixel_fraction < 1
    # Measured, and nothing at the end of the scale: 0.0, never None ("not measured")
    assert (stored[clean.pk].saturated_pixel_fraction, stored[clean.pk].saturated) == (0.0, False)
    # The ladder marker is measured saturated; the page's check leaves LADDER lanes out. A band without a
    # band_number is named by its rank from the top of its lane.
    assert stored[marker.pk].saturated is True
    assert saturated_bands(Lane.objects.filter(analysis=gel_analysis)) == [(3, 1, "POI")]

    # A re-run fills a stored row again (the bulk_update path), e.g. one integrated before the check existed.
    DensitometryResult.objects.filter(band__lane__analysis=gel_analysis).update(saturated_pixel_fraction=None)
    DensitometryService().analyze_and_save(gel_analysis, display, test_user, original_image=original)
    assert DensitometryResult.objects.get(band=clipped).saturated is True
