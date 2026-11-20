"""Tilted lanes, plan 2b (spec docs/superpowers/specs/2026-10-10-gel-lane-tilt-design.md §4 Rule 2, §5.1): the pages and
the reports read a lane by its outline -- its polygon unless it is a RECTANGLE -- never by a stale stored box, and never
by the polygon a RECTANGLE lane may still carry."""

import pytest
from PIL import Image, ImageChops

from django.urls import reverse

from gel_analyzer.models import Lane, SavedComparison, SavedComparisonLane
from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector
from gel_analyzer.services.report.data_collector import ReportDataCollector
from gel_analyzer.services.report.lane_crop import crop_lane
from gel_analyzer.views.comparison import _serialize_lane_data

Q_POLYGON = [[50, 10], [90, 10], [150, 490], [110, 490]]
R_BOX_CORNERS = [[200, 10], [240, 10], [240, 490], [200, 490]]


def _legacy_lanes(analysis):
    """A tilted lane whose stored box no longer matches its polygon (a lane saved before Rule 1), and a RECTANGLE lane
    still carrying a polygon. ``objects.create`` stores them as given: no Rule 1 on this path."""
    tilted = Lane.objects.create(
        analysis=analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        lane_shape=Lane.LaneShape.QUADRILATERAL,
        polygon=Q_POLYGON,
        x=50,
        y=10,
        width=40,
        height=480,
    )
    rectangle = Lane.objects.create(
        analysis=analysis,
        lane_number=2,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        lane_shape=Lane.LaneShape.RECTANGLE,
        polygon=[[300, 10], [340, 10], [340, 490], [300, 490]],
        x=200,
        y=10,
        width=40,
        height=480,
    )
    return tilted, rectangle


@pytest.mark.django_db
def test_comparison_payloads_give_the_outline_not_a_rectangles_stale_polygon(client, gel_analysis, test_user):
    tilted, rectangle = _legacy_lanes(gel_analysis)
    client.force_login(test_user)

    for lane, expected in ((tilted, Q_POLYGON), (rectangle, R_BOX_CORNERS)):
        resolved = _serialize_lane_data(lane)["lane"]["outline"]
        added = client.get(reverse("gel_analyzer:api_lane_comparison_data", kwargs={"pk": lane.pk})).json()["lane"]
        assert resolved == expected
        assert added["outline"] == expected  # the "Add lane" endpoint, through the same lane_item


@pytest.mark.django_db
def test_report_crop_of_a_legacy_tilted_lane_is_its_masked_outline_and_a_rectangles_stale_polygon_is_ignored(
    gel_analysis, test_user
):
    tilted, rectangle = _legacy_lanes(gel_analysis)
    upright = Lane.objects.create(  # a Straight accept from the lane review: a 4-point POLYGON that is its box
        analysis=gel_analysis,
        lane_number=3,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        lane_shape=Lane.LaneShape.POLYGON,
        polygon=[[300, 10], [340, 10], [340, 490], [300, 490]],
        x=300,
        y=10,
        width=40,
        height=480,
    )
    comparison = SavedComparison.objects.create(name="Tilted", created_by=test_user)
    for order, lane in enumerate((tilted, rectangle, upright)):
        SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=order)
    rows = {row.lane_number: row for row in ComparisonDataCollector().collect(comparison, test_user).lanes}

    background, band, neighbour = (30, 30, 30), (150, 150, 150), (220, 220, 220)
    src = Image.new("RGB", (400, 500), background)
    src.paste(band, (60, 45, 90, 56))  # inside the tilted lane
    src.paste(neighbour, (120, 20, 141, 121))  # inside its outline's box, outside the lane
    src.paste(neighbour, (297, 0, 300, 500))  # the upright lane's left padding

    crop, box = crop_lane(src, rows[1], 15, 3, 30, 3)
    assert box == (44, 0, 156, 500)  # the outline's outer box, padded -- the stale stored box gives (47, 0, 93, 500)
    assert crop.getpixel((75 - 44, 50)) == band
    assert crop.getpixel((130 - 44, 50)) == background  # the neighbour is masked with the crop's median

    assert rows[2].polygon is None
    crop, box = crop_lane(src, rows[2], 15, 3, 30, 3)
    assert box == (197, 0, 243, 500)
    assert ImageChops.difference(crop, src.crop(box)).getbbox() is None  # a box: nothing masked

    # An upright 4-point lane is its box: its crop keeps its padding, as before tilted lanes existed.
    crop, box = crop_lane(src, rows[3], 15, 3, 30, 3)
    assert box == (297, 0, 343, 500)
    assert ImageChops.difference(crop, src.crop(box)).getbbox() is None

    # The single-analysis report's collector applies the same rule.
    polygons = [lane.polygon for lane in ReportDataCollector().collect(gel_analysis, test_user).lanes]
    assert polygons == [Q_POLYGON, None, upright.polygon]
