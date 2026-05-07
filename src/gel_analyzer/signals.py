"""Signal handlers for gel_analyzer."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from phoresis_core.logging_config import get_logger

from .models import Band, GelImage

logger = get_logger(__name__)


def invalidate_lane_densitometry(lane_id: int) -> None:
    """
    Drop cached densitometry for a lane after one of its bands changed.

    Two pieces become stale the moment the band set of a lane changes:

    1. ``LaneDensitometrySummary`` aggregates (``total_integrated_area``,
       ``poi_percentage``, ``band_count``, ``profile_data``) — they were
       computed against the *previous* set of bands.
    2. ``DensitometryResult.relative_percent_lane`` of the *sibling* bands —
       they were normalized against a now-outdated lane total.

    The deleted band's own ``DensitometryResult`` is already gone via the
    ``OneToOneField(on_delete=CASCADE)`` declared on ``DensitometryResult``;
    we don't need to re-delete it. Wiping the lane summary + sibling rows
    makes the densitometry view show "no results" until the user clicks
    Run Analysis again — which is the only way to get scientifically
    consistent quantification after a band edit / split / create.

    Idempotent: ``filter().delete()`` is a no-op if nothing matches, so it
    is safe to call from cascade-delete paths where the rows may already
    be gone.

    Designed to be cheap: 2 DELETE statements scoped to one lane. The
    user explicitly asked for this in the densitometry-stale-after-split
    debug session — see commit message for context.
    """
    # Local import: signals module is loaded by AppConfig.ready(), at which
    # point importing densitometry models at module-top would create an
    # app-loading cycle.
    from .models import DensitometryResult, LaneDensitometrySummary

    if lane_id is None:
        return

    summary_deleted, _ = LaneDensitometrySummary.objects.filter(lane_id=lane_id).delete()
    siblings_deleted, _ = DensitometryResult.objects.filter(band__lane_id=lane_id).delete()

    if summary_deleted or siblings_deleted:
        logger.debug(
            f"Invalidated densitometry for lane {lane_id}: "
            f"{summary_deleted} summary, {siblings_deleted} sibling band results"
        )


@receiver(post_save, sender=Band)
def invalidate_densitometry_on_band_save(sender, instance: Band, **kwargs) -> None:
    """
    Wipe the lane's cached densitometry whenever a band is created or saved.

    Triggers on: manual band creation, polygon edits, bbox moves, band-type
    changes, label edits — anything that goes through ``Band.save()``.

    Does NOT fire on ``Band.objects.bulk_create()`` /
    ``Band.objects.bulk_update()`` (Django gotcha). Callers using those
    bulk paths must invoke ``invalidate_lane_densitometry`` manually —
    today that means ``services.band_detection.cross_lane_consensus`` and
    the densitometry service's own ``intensity_normalized`` write-back
    (which is intentionally kept out of the invalidation loop, otherwise
    each Run Analysis would erase the rows it just wrote).
    """
    invalidate_lane_densitometry(instance.lane_id)


@receiver(post_delete, sender=Band)
def invalidate_densitometry_on_band_delete(sender, instance: Band, **kwargs) -> None:
    """
    Wipe the lane's cached densitometry when a band is removed.

    Fires for direct deletes and for cascade-deletes (lane removed,
    analysis removed). The cascade case does extra work — the lane and
    its summary are about to be torn down anyway — but the cost is one
    no-op DELETE per band, well below the noise of the surrounding
    cascade.
    """
    invalidate_lane_densitometry(instance.lane_id)


@receiver(post_delete, sender=GelImage)
def delete_gel_image_files(sender, instance: GelImage, **kwargs) -> None:
    """
    Delete the original / display / thumbnail files from storage when a
    GelImage row is removed.

    Django does NOT auto-delete FieldFile content on `model.delete()` — the
    row vanishes, the bytes stay. This leaks media files every time a user
    deletes an image from the UI / admin and every time the orphan-purge
    task (`gel_analyzer.tasks.purge_orphan_gel_images`) sweeps abandoned
    uploads. We hook post_delete (rather than override `Model.delete`) so
    QuerySet.delete() and cascade-deletes also clean up.

    Errors are swallowed at WARN level: the row is already gone, so a
    storage hiccup must not raise. The orphan files become disk garbage
    we can sweep later, never a transactional failure.
    """
    for field_name in ("original_file", "display_file", "thumbnail"):
        fieldfile = getattr(instance, field_name, None)
        name = getattr(fieldfile, "name", None) if fieldfile else None
        if not name:
            continue
        try:
            fieldfile.storage.delete(name)
        except Exception as exc:
            logger.warning(f"GelImage {instance.pk} post_delete: could not remove {field_name}={name!r}: {exc}")
