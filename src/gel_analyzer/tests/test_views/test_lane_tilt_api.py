"""lanes/tilt/: the review's "Follow the lanes" gets each detected lane's guarded mask slope (spec 2026-10-10 §10).

The view must run the app's rule (mask_guarded, 4 px), not the bench's module defaults: the cases below are chosen
so that a lost keyword tilts a lane the app keeps straight.
"""

import json

import cv2
import numpy as np
import pytest

from django.core.files.base import ContentFile
from django.urls import reverse


def _display_with_a_tilted_stripe(gel_image):
    """A 400x500 display file: a flat background and one clean bright stripe drifting +0.075 px per row."""
    gray = np.full((500, 400), 30, dtype=np.uint8)
    for row in range(50, 450):
        centre = 100 + 0.075 * (row - 250)
        columns = np.arange(400)
        gray[row] = np.clip(30 + 150 * np.exp(-((columns - centre) ** 2) / (2 * 6**2)), 0, 255).astype(np.uint8)
    ok, png = cv2.imencode(".png", gray)
    assert ok
    gel_image.display_file.save("tilt_display.png", ContentFile(png.tobytes()), save=True)


@pytest.mark.django_db
def test_lane_tilt_keeps_the_mask_slope_unless_the_image_contradicts_it(client, test_user, gel_analysis):
    url = reverse("gel_analyzer:api_lane_tilt", kwargs={"pk": gel_analysis.pk})
    assert client.post(url, data="{}", content_type="application/json").status_code == 302  # signed-in only

    client.force_login(test_user)
    refused = client.post(url, data=json.dumps({"token": "t", "boxes": []}), content_type="application/json")
    assert refused.status_code == 400 and "Invalid lanes" in refused.json()["error"]

    _display_with_a_tilted_stripe(gel_analysis.gel_image)
    boxes = [
        {"index": 0, "box": [70, 50, 60, 400], "mask_slope": -0.075},  # the stripe, mask says the opposite
        {"index": 1, "box": [250, 50, 60, 400], "mask_slope": 0.05},  # flat: nothing contradicts the mask
        {"index": 2, "box": [330, 50, 60, 400], "mask_slope": None},  # no mask axis
        {"index": 3, "box": [250, 50, 60, 400], "mask_slope": 0.0075},  # 3 px over 400 rows: under the app's 4 px
        {"index": 4, "box": [250, 50, 60, 400], "mask_slope": 0.2},  # a degenerate mask, past the 0.15 bound
    ]
    response = client.post(url, data=json.dumps({"token": "review-7", "boxes": boxes}), content_type="application/json")

    assert response.status_code == 200, response.content
    data = response.json()
    assert set(data) == {"success", "token", "y_ref", "lanes"} and data["token"] == "review-7"
    lanes = {lane["index"]: lane for lane in data["lanes"]}
    assert all(set(lane) == {"index", "x_ref", "slope", "width", "source"} for lane in lanes.values())
    assert (lanes[0]["source"], lanes[0]["slope"]) == ("straight", 0.0)  # contradicted by a reliable +0.075
    assert (lanes[1]["source"], lanes[1]["slope"]) == ("mask", 0.05)
    assert [(lanes[i]["source"], lanes[i]["slope"]) for i in (2, 3, 4)] == [("straight", 0.0)] * 3
