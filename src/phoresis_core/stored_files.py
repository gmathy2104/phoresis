"""
Replacing or deleting a row's own stored file without leaving the old blob behind, or taking another row's.

The media storage never overwrites a name that is taken
(``AzureMediaStorage.overwrite_files = False``, ``FileSystemStorage`` by
design): saving a FileField under a name that already exists stores
``name_<random>.ext`` instead, and the blob it replaces stays in the container
with no row pointing at it. Code that regenerates its own file (a thumbnail, a
re-rendered image, a regenerated worklist) captures the old name, writes the
new file, saves the row, then calls ``delete_replaced_file``.
"""

from __future__ import annotations

from django.apps import apps
from django.db import models, transaction
from django.db.models import Q

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


def _model_still_naming(name: str):
    """The first model with a row whose file field holds ``name``, or None.

    Every managed model is asked, not only the replacing one: a name can be
    shared across models (a common ``upload_to`` folder, a name assigned by
    hand in an import), and the cost is paid only after a real replacement.
    """
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed:
            continue
        still_named = Q()
        for field in model._meta.local_concrete_fields:
            if isinstance(field, models.FileField):
                still_named |= Q(**{field.name: name})
        if still_named and model._base_manager.filter(still_named).exists():
            return model
    return None


def delete_replaced_file(field_file, old_name: str | None) -> None:
    """Delete ``old_name`` from storage once no row names it any more.

    Call it AFTER the new file is written AND the row saved with its new name:
    never delete first, a failed write would then lose both files.

    - Nothing happens when the name did not change (or there was no old file).
    - The deletion waits for the transaction to commit. A rollback puts the old
      name back in the row, so the old blob must survive it.
    - It is skipped while any row of any model still names ``old_name`` in a
      file field. Before ``overwrite_files`` was turned off, two uploads of one
      name shared ONE blob; deleting it on behalf of one row would break the
      other. (History tables store names as text and are not consulted.)
    - A failed delete is logged, never raised: the new file is in place, and a
      leftover blob is a leak, not a loss.
    """
    if not old_name or old_name == field_file.name:
        return
    _delete_once_unnamed(field_file.storage, old_name)


def delete_file_of_deleted_row(field_file) -> None:
    """Delete the file of a row being deleted, once no row names it any more.

    Call it inside the ``transaction.atomic()`` that deletes the row: the deletion waits for the commit, and the row must
    be gone by then. The same rules as ``delete_replaced_file``: a rollback keeps the file, and a file another row still
    names stays, which is what a plain ``field_file.delete()`` gets wrong for two uploads of one name sharing ONE blob.
    """
    if field_file.name:
        _delete_once_unnamed(field_file.storage, field_file.name)


def _delete_once_unnamed(storage, name: str) -> None:
    def _delete():
        try:
            holder = _model_still_naming(name)
            if holder is not None:
                logger.info(f"Kept file {name}: a {holder.__name__} row still points at it")
                return
            storage.delete(name)
        except Exception:  # noqa: BLE001 -- the row's change is saved; the blob only leaks
            logger.exception(f"Could not delete file {name}")

    transaction.on_commit(_delete)
