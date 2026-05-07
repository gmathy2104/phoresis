"""
Tests for the Band-change → densitometry-cache invalidation pipeline.

The signal handlers in ``gel_analyzer.signals`` must wipe both the
``LaneDensitometrySummary`` of the affected lane AND the ``DensitometryResult``
of every other band in that lane (their ``relative_percent_lane`` was
normalized against an outdated lane total).

Without this, splitting / creating / deleting a band in the Annotation module
leaves stale aggregates on the densitometry page — exactly the bug this
branch is fixing.
"""

from __future__ import annotations

import pytest

from gel_analyzer.models import (
    Band,
    DensitometryResult,
    LaneDensitometrySummary,
)
from gel_analyzer.signals import invalidate_lane_densitometry

pytestmark = pytest.mark.django_db


@pytest.fixture
def lane_with_densitometry(sample_lane, test_user):
    """Two bands with densitometry results + a lane summary, ready to be invalidated."""
    band_a = Band.objects.create(
        lane=sample_lane,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=100,
        bbox_x=50,
        bbox_y=90,
        bbox_width=40,
        bbox_height=20,
        created_by=test_user,
    )
    band_b = Band.objects.create(
        lane=sample_lane,
        detection_source=Band.DetectionSource.MANUAL,
        position_y=200,
        bbox_x=50,
        bbox_y=190,
        bbox_width=40,
        bbox_height=20,
        created_by=test_user,
    )

    # Re-fetch so ``LaneDensitometrySummary`` is fresh — the create() above
    # fired the post_save signal which deleted any pre-existing summary.
    LaneDensitometrySummary.objects.create(
        lane=sample_lane,
        total_integrated_area=1000.0,
        band_count=2,
    )
    DensitometryResult.objects.create(
        band=band_a,
        peak_center_y=100.0,
        peak_amplitude=50.0,
        peak_sigma=5.0,
        fwhm=11.77,
        integrated_area=500.0,
        corrected_area=500.0,
        fit_r_squared=0.99,
        snr=20.0,
    )
    DensitometryResult.objects.create(
        band=band_b,
        peak_center_y=200.0,
        peak_amplitude=50.0,
        peak_sigma=5.0,
        fwhm=11.77,
        integrated_area=500.0,
        corrected_area=500.0,
        fit_r_squared=0.99,
        snr=20.0,
    )

    return {"lane": sample_lane, "band_a": band_a, "band_b": band_b}


class TestInvalidateLaneDensitometry:
    """Direct calls to the helper — drives the cleanup logic in isolation."""

    def test_wipes_lane_summary(self, lane_with_densitometry):
        lane = lane_with_densitometry["lane"]
        assert LaneDensitometrySummary.objects.filter(lane=lane).exists()

        invalidate_lane_densitometry(lane.id)

        assert not LaneDensitometrySummary.objects.filter(lane=lane).exists()

    def test_wipes_sibling_densitometry_results(self, lane_with_densitometry):
        lane = lane_with_densitometry["lane"]
        assert DensitometryResult.objects.filter(band__lane=lane).count() == 2

        invalidate_lane_densitometry(lane.id)

        assert DensitometryResult.objects.filter(band__lane=lane).count() == 0

    def test_none_lane_id_is_noop(self):
        """Defensive: ``None`` lane_id (e.g. unsaved instance) must not raise."""
        # Should not raise
        invalidate_lane_densitometry(None)

    def test_unknown_lane_id_is_noop(self, lane_with_densitometry):
        """Unrelated lane_id must not affect existing rows."""
        lane = lane_with_densitometry["lane"]
        invalidate_lane_densitometry(lane.id + 9999)

        assert LaneDensitometrySummary.objects.filter(lane=lane).exists()
        assert DensitometryResult.objects.filter(band__lane=lane).count() == 2


class TestBandSignalsInvalidate:
    """End-to-end: editing bands through the ORM must invalidate via signal."""

    def test_band_create_wipes_summary(self, sample_lane, test_user):
        """Creating a new band wipes the lane's previous summary (= bug fix)."""
        LaneDensitometrySummary.objects.create(
            lane=sample_lane,
            total_integrated_area=1234.5,
            band_count=0,
        )
        assert LaneDensitometrySummary.objects.filter(lane=sample_lane).exists()

        Band.objects.create(
            lane=sample_lane,
            detection_source=Band.DetectionSource.MANUAL,
            position_y=150,
            bbox_x=50,
            bbox_y=140,
            bbox_width=40,
            bbox_height=20,
            created_by=test_user,
        )

        assert not LaneDensitometrySummary.objects.filter(lane=sample_lane).exists()

    def test_band_save_wipes_summary(self, lane_with_densitometry):
        """Editing an existing band (e.g. polygon move) also invalidates."""
        lane = lane_with_densitometry["lane"]
        band = lane_with_densitometry["band_a"]

        band.position_y = 105
        band.save()

        assert not LaneDensitometrySummary.objects.filter(lane=lane).exists()
        assert DensitometryResult.objects.filter(band__lane=lane).count() == 0

    def test_band_delete_wipes_sibling_densitometry(self, lane_with_densitometry):
        """Deleting one band must wipe the OTHER band's densitometry too.

        Otherwise the surviving band keeps a ``relative_percent_lane`` that
        was computed against a lane total which no longer exists.
        """
        lane = lane_with_densitometry["lane"]
        band_a = lane_with_densitometry["band_a"]

        band_a.delete()

        # Band B's DensitometryResult should also be gone — its percentage
        # was relative to a lane total that included band A.
        assert DensitometryResult.objects.filter(band__lane=lane).count() == 0
        assert not LaneDensitometrySummary.objects.filter(lane=lane).exists()

    def test_split_simulation_clears_stale_aggregates(self, lane_with_densitometry):
        """Simulate the band-split flow: delete original, create two halves.

        Mirrors what ``gel-viewer.js:_splitBand`` does over HTTP. After this
        sequence the lane must have NO leftover summary or sibling DR rows
        — those are the bytes the user used to see as "à côté de la plaque".
        """
        lane = lane_with_densitometry["lane"]
        band_a = lane_with_densitometry["band_a"]

        # 1) DELETE the original band (cascade kills its DR; signal kills the
        # rest)
        band_a.delete()

        # 2) CREATE the two halves
        Band.objects.create(
            lane=lane,
            detection_source=Band.DetectionSource.MANUAL,
            position_y=95,
            bbox_x=50,
            bbox_y=90,
            bbox_width=40,
            bbox_height=10,
        )
        Band.objects.create(
            lane=lane,
            detection_source=Band.DetectionSource.MANUAL,
            position_y=105,
            bbox_x=50,
            bbox_y=100,
            bbox_width=40,
            bbox_height=10,
        )

        # No leftover summary, no leftover sibling-DR. Run Analysis must
        # rebuild from scratch.
        assert not LaneDensitometrySummary.objects.filter(lane=lane).exists()
        assert DensitometryResult.objects.filter(band__lane=lane).count() == 0
