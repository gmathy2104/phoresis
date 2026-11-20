"""Comparison Word report: the lane composite (gel crop | digital lane | MW scale)."""

import io

import numpy as np
import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from gel_analyzer.models import Band, Lane, SavedComparison, SavedComparisonLane
from gel_analyzer.services.report.comparison_builder import ComparisonReportBuilder
from gel_analyzer.services.report.comparison_data_collector import ComparisonDataCollector

pytestmark = pytest.mark.django_db


def test_band_without_mw_divided_by_lane_height_is_marked_level_with_the_crop(gel_analysis, test_user):
    """Bug: a band without an MW was placed at `position_y / lane.height`, but position_y is
    an absolute image row: in a lane not starting at y = 0 every mark was pushed down and
    clamped at the bottom of the digital column, away from its band in the crop beside it.

    Bug: the MW column beside those marks drew a 10-250 kDa ruler, unrelated to their rows:
    a band read as an MW the lab never estimated."""
    # The conftest gel has bright stripes 10 px tall at y = 100, 150, 200, 300, 400.
    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=1,
        lane_type=Lane.LaneType.SAMPLE,
        detection_source=Lane.DetectionSource.MANUAL,
        x=60,
        y=120,
        width=60,
        height=330,
        sample_name="S1",
    )
    for y in (150, 200, 300, 400):
        Band.objects.create(lane=lane, position_y=y)
    comparison = SavedComparison.objects.create(name="Cmp", created_by=test_user)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=lane, order=0)
    data = ComparisonDataCollector().collect(comparison, test_user)

    doc = Document(ComparisonReportBuilder(data, sections=["lane_details"]).build())
    paragraphs = doc.paragraphs
    label = next(i for i, p in enumerate(paragraphs) if p.text == "Gel View & Digital Lane:")
    blip = paragraphs[label + 1]._p.xpath(".//a:blip")[0]
    composite = Image.open(io.BytesIO(doc.part.related_parts[blip.get(qn("r:embed"))].blob))
    img = np.asarray(composite.convert("RGB"), dtype=int)

    # The band marks are the only coloured pixels below the label row and the column
    # header (whose accent bar is coloured); the gel crop is grey.
    coloured = (img.max(axis=2) - img.min(axis=2)) > 40
    coloured[: 20 + 28] = False
    rows, cols = np.nonzero(coloured)
    mark_rows = np.unique(rows)
    marks = [int(g.mean()) for g in np.split(mark_rows, np.nonzero(np.diff(mark_rows) > 1)[0] + 1)]
    crop = img[:, : cols.min() - 20, 0]

    assert len(marks) == 4
    for row in marks:
        assert crop[row].mean() > 128, f"mark at row {row} is not on a band of the crop"

    # The MW column (65 px, rightmost) is background below its "No MW calibration" label.
    assert (img[20 + 28 + 40 :, -65:] == (30, 30, 34)).all(), "no-MW lane drew a kDa ruler the lab never estimated"
