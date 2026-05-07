"""Signal handlers for gel_analyzer."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from phoresis_core.logging_config import get_logger

from .models import GelImage

logger = get_logger(__name__)


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
