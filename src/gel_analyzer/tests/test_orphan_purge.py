"""
Tests for the orphan-GelImage cleanup pipeline:

- ``gel_analyzer.signals.delete_gel_image_files`` — post_delete signal
  that wipes original / display / thumbnail files when a row is removed.
- ``gel_analyzer.tasks.purge_orphan_gel_images`` — periodic task that
  removes GelImage rows uploaded but never attached to an analysis.

Together they close the leak where a user uploads a file via /images/upload/
then closes the browser without creating an analysis.
"""

import io
from datetime import timedelta

import pytest
from PIL import Image

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from gel_analyzer.models import GelAnalysis, GelImage
from gel_analyzer.tasks import purge_orphan_gel_images


def _png_bytes() -> bytes:
    img = Image.new("L", (8, 8), color=128)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def gel_image_with_files(db, test_user):
    """A GelImage with all three files populated (original/display/thumbnail)."""
    gi = GelImage.objects.create(
        original_file=SimpleUploadedFile("orig.png", _png_bytes(), content_type="image/png"),
        original_filename="orig.png",
        file_format=GelImage.FileFormat.PNG,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=test_user,
    )
    gi.display_file.save("display.png", ContentFile(_png_bytes()), save=False)
    gi.thumbnail.save("thumb.png", ContentFile(_png_bytes()), save=False)
    gi.save()
    return gi


# ── post_delete signal ───────────────────────────────────────────────────


def test_post_delete_removes_all_three_files(gel_image_with_files):
    gi = gel_image_with_files
    paths = [gi.original_file, gi.display_file, gi.thumbnail]
    storage = paths[0].storage
    names = [f.name for f in paths]

    for name in names:
        assert storage.exists(name), f"precondition: {name} should exist before delete"

    gi.delete()

    for name in names:
        assert not storage.exists(name), f"{name} still on disk after GelImage.delete()"


def test_post_delete_with_missing_files_does_not_raise(db, test_user):
    """A row with empty FileFields (or files already missing on disk) must
    not blow up the delete — the signal swallows storage errors."""
    gi = GelImage.objects.create(
        original_file=SimpleUploadedFile("o.png", _png_bytes()),
        original_filename="o.png",
        file_format=GelImage.FileFormat.PNG,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=test_user,
    )
    # Wipe the underlying file out-of-band, then delete the row.
    gi.original_file.storage.delete(gi.original_file.name)
    gi.delete()  # should not raise


def test_queryset_delete_also_cleans_files(db, test_user):
    """`QuerySet.delete()` must also fire post_delete -> cleanup."""
    images = []
    for i in range(3):
        gi = GelImage.objects.create(
            original_file=SimpleUploadedFile(f"q{i}.png", _png_bytes()),
            original_filename=f"q{i}.png",
            file_format=GelImage.FileFormat.PNG,
            gel_type=GelImage.GelType.SDS_PAGE,
            uploaded_by=test_user,
        )
        images.append(gi)

    storage = images[0].original_file.storage
    names = [gi.original_file.name for gi in images]
    assert all(storage.exists(n) for n in names)

    GelImage.objects.filter(pk__in=[gi.pk for gi in images]).delete()

    assert not any(storage.exists(n) for n in names)


# ── purge_orphan_gel_images task ─────────────────────────────────────────


def _backdate_upload(gi: GelImage, hours_ago: int) -> None:
    """`uploaded_at` is auto_now_add — bypass via UPDATE."""
    GelImage.objects.filter(pk=gi.pk).update(uploaded_at=timezone.now() - timedelta(hours=hours_ago))


def test_purge_removes_old_orphan(gel_image_with_files):
    _backdate_upload(gel_image_with_files, hours_ago=48)
    storage = gel_image_with_files.original_file.storage
    name = gel_image_with_files.original_file.name

    result = purge_orphan_gel_images(ttl_hours=24)

    assert result["found"] == 1
    assert result["deleted"] == 1
    assert not GelImage.objects.filter(pk=gel_image_with_files.pk).exists()
    assert not storage.exists(name)


def test_purge_keeps_recent_orphan(gel_image_with_files):
    """Recent upload (< TTL) must not be purged — user might still come back."""
    # uploaded_at is "now"; default TTL is 24 h.
    result = purge_orphan_gel_images(ttl_hours=24)

    assert result["found"] == 0
    assert result["deleted"] == 0
    assert GelImage.objects.filter(pk=gel_image_with_files.pk).exists()


def test_purge_keeps_image_with_analysis(gel_image_with_files, test_user):
    """An image attached to ANY analysis is no longer orphan, regardless of age."""
    GelAnalysis.objects.create(
        gel_image=gel_image_with_files,
        name="t",
        status=GelAnalysis.Status.DRAFT,
        created_by=test_user,
    )
    _backdate_upload(gel_image_with_files, hours_ago=240)  # 10 days old

    result = purge_orphan_gel_images(ttl_hours=24)

    assert result["found"] == 0
    assert GelImage.objects.filter(pk=gel_image_with_files.pk).exists()


def test_purge_one_bad_row_doesnt_stop_the_sweep(db, test_user, monkeypatch):
    """If one row's delete raises, the others still get purged."""
    images = []
    for i in range(3):
        gi = GelImage.objects.create(
            original_file=SimpleUploadedFile(f"b{i}.png", _png_bytes()),
            original_filename=f"b{i}.png",
            file_format=GelImage.FileFormat.PNG,
            gel_type=GelImage.GelType.SDS_PAGE,
            uploaded_by=test_user,
        )
        _backdate_upload(gi, hours_ago=48)
        images.append(gi)

    poison_pk = images[1].pk

    original_delete = GelImage.delete

    def patched(self, *args, **kwargs):
        if self.pk == poison_pk:
            raise RuntimeError("simulated failure")
        return original_delete(self, *args, **kwargs)

    monkeypatch.setattr(GelImage, "delete", patched)

    result = purge_orphan_gel_images(ttl_hours=24)

    assert result["found"] == 3
    assert result["deleted"] == 2
    # Poisoned row must still exist; the other two must be gone.
    assert GelImage.objects.filter(pk=poison_pk).exists()
    assert not GelImage.objects.filter(pk=images[0].pk).exists()
    assert not GelImage.objects.filter(pk=images[2].pk).exists()
