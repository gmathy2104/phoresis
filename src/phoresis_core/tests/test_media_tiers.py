"""Media on two disks: the storage, the archive pass, the command (phoresis_core.media_tiers)."""

import os
import time

import pytest

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from phoresis_core import media_tiers
from phoresis_core.media_tiers import ArchiveOfflineError, TieredMediaStorage
from phoresis_core.models import ArchivedMediaFile

GB = 1024**3
OLD = time.time() - 90 * 86400


@pytest.fixture
def tiers(tmp_path, settings):
    """A fast disk and a prepared archive, both in tmp_path; quota 1000 bytes, no free-space floor."""
    cache.clear()
    hot, cold = tmp_path / "hot", tmp_path / "archive disk"  # a space, like "/Volumes/Samsung T7"
    hot.mkdir()
    settings.MEDIA_ROOT = str(hot)
    settings.PHORESIS_MEDIA_ARCHIVE_ROOT = str(cold)
    settings.PHORESIS_MEDIA_HOT_QUOTA_BYTES = 1000
    settings.PHORESIS_MEDIA_MIN_FREE_BYTES = 0
    settings.PHORESIS_MEDIA_ARCHIVE_MIN_FREE_BYTES = 0
    settings.PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS = 30
    settings.PHORESIS_MEDIA_ARCHIVE_PREFIXES = ["gel_images/originals/"]
    media_tiers.prepare_archive_root()
    return hot, cold


def put(hot, name: str, size: int, *, mtime: float = OLD) -> None:
    path = hot / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    os.utime(path, (mtime, mtime))


def unplug(cold) -> None:
    (cold / media_tiers.MARKER_NAME).unlink()


# ───────────── archive state ─────────────


def test_disabled_without_an_archive_root(settings):
    settings.PHORESIS_MEDIA_ARCHIVE_ROOT = ""
    assert media_tiers.archive_state().state == media_tiers.DISABLED
    assert media_tiers.archive_pass()["reason"] == "no archive configured"


def test_a_folder_without_its_marker_is_not_an_archive(tiers):
    _hot, cold = tiers
    assert media_tiers.archive_state().ready
    unplug(cold)
    assert media_tiers.archive_state().state == media_tiers.UNPREPARED


def test_an_unmounted_volume_is_offline_and_is_never_created(settings):
    settings.PHORESIS_MEDIA_ARCHIVE_ROOT = "/Volumes/phoresis-no-such-disk/Phoresis/media"
    assert media_tiers.archive_state().state == media_tiers.OFFLINE
    with pytest.raises(ValueError, match="not connected"):
        media_tiers.prepare_archive_root()
    assert not os.path.exists("/Volumes/phoresis-no-such-disk")


# ───────────── archive pass ─────────────


@pytest.mark.django_db
def test_nothing_moves_under_quota(tiers):
    hot, _cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 400)
    result = media_tiers.archive_pass()
    assert (result["moved_files"], result["reason"]) == (0, "under quota")
    assert (hot / "gel_images/originals/2026/01/a.tif").exists()


@pytest.mark.django_db
def test_oldest_originals_leave_first_until_under_quota(tiers):
    hot, cold = tiers
    put(hot, "gel_images/originals/2026/01/oldest.tif", 500, mtime=OLD - 1000)
    put(hot, "gel_images/originals/2026/02/older.tif", 500, mtime=OLD)
    put(hot, "gel_images/originals/2026/11/recent.tif", 500, mtime=time.time())
    put(hot, "gel_images/display/2026/01/oldest.png", 100, mtime=OLD - 1000)
    content = (hot / "gel_images/originals/2026/01/oldest.tif").read_bytes()

    result = media_tiers.archive_pass()

    # 1600 used, quota 1000, margin 100: 700 to free, so the two old originals go (the 2nd one overshoots).
    assert result["moved_files"] == 2
    assert not (hot / "gel_images/originals/2026/01/oldest.tif").exists()
    assert (cold / "gel_images/originals/2026/01/oldest.tif").read_bytes() == content
    assert (hot / "gel_images/originals/2026/11/recent.tif").exists(), "younger than the minimum age"
    assert (hot / "gel_images/display/2026/01/oldest.png").exists(), "not an archivable prefix"
    record = ArchivedMediaFile.objects.get(name="gel_images/originals/2026/01/oldest.tif")
    assert record.size_bytes == 500 and len(record.sha256) == 64
    assert not list(cold.rglob("*.part"))


@pytest.mark.django_db
def test_says_so_when_only_recent_files_are_left(tiers):
    hot, _cold = tiers
    put(hot, "gel_images/originals/2026/11/recent.tif", 2000, mtime=time.time())
    result = media_tiers.archive_pass()
    assert result["moved_files"] == 0
    assert result["still_needed_bytes"] > 0
    assert "nothing older than 30 days" in result["reason"]


@pytest.mark.django_db
def test_no_archiving_and_no_writing_while_the_disk_is_away(tiers):
    hot, cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    unplug(cold)
    result = media_tiers.archive_pass()
    assert result["moved_files"] == 0 and "not available" in result["reason"]
    assert (hot / "gel_images/originals/2026/01/a.tif").exists()
    assert not (cold / "gel_images").exists()


@pytest.mark.django_db
def test_stops_before_filling_the_archive_disk(tiers, settings):
    hot, _cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    settings.PHORESIS_MEDIA_ARCHIVE_MIN_FREE_BYTES = 10**18
    result = media_tiers.archive_pass()
    assert result["moved_files"] == 0 and result["reason"] == "archive disk is full"
    assert (hot / "gel_images/originals/2026/01/a.tif").exists()


@pytest.mark.django_db
def test_a_copy_that_does_not_match_keeps_the_original(tiers, monkeypatch):
    hot, cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    monkeypatch.setattr(media_tiers, "_sha256", lambda path: "0" * 64)
    result = media_tiers.archive_pass()
    assert result["moved_files"] == 0 and "does not match" in result["reason"]
    assert (hot / "gel_images/originals/2026/01/a.tif").exists()
    assert not ArchivedMediaFile.objects.exists()
    assert not [p for p in cold.rglob("*") if p.is_file() and p.name != media_tiers.MARKER_NAME]


@pytest.mark.django_db
def test_dry_run_moves_nothing(tiers):
    hot, _cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    result = media_tiers.archive_pass(dry_run=True)
    assert result["moved_files"] == 1
    assert (hot / "gel_images/originals/2026/01/a.tif").exists()
    assert not ArchivedMediaFile.objects.exists()


@pytest.mark.django_db
def test_low_free_space_triggers_archiving_under_quota(tiers, settings):
    hot, cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 400)
    settings.PHORESIS_MEDIA_MIN_FREE_BYTES = 10**18  # no disk has that much free
    assert media_tiers.archive_pass()["moved_files"] == 1
    assert (cold / "gel_images/originals/2026/01/a.tif").exists()


# ───────────── storage ─────────────


@pytest.fixture
def archived(tiers):
    """One original, archived; returns (storage, name, content, hot, cold)."""
    hot, cold = tiers
    name = "gel_images/originals/2026/01/a.tif"
    put(hot, name, 2000)
    content = (hot / name).read_bytes()
    assert media_tiers.archive_pass()["moved_files"] == 1
    return TieredMediaStorage(), name, content, hot, cold


@pytest.mark.django_db
def test_an_archived_file_reads_like_any_other(archived):
    storage, name, content, _hot, cold = archived
    assert storage.exists(name)
    assert storage.size(name) == 2000
    assert storage.path(name) == str(cold / name)
    with storage.open(name) as fh:
        assert fh.read() == content
    assert storage.url(name) == f"/media/{name}"


@pytest.mark.django_db
def test_with_the_disk_away_the_name_stays_taken_and_the_error_says_why(archived):
    storage, name, _content, hot, cold = archived
    unplug(cold)
    assert storage.exists(name)
    with pytest.raises(ArchiveOfflineError, match="Reconnect the disk"):
        storage.open(name)
    saved = storage.save(name, ContentFile(b"another gel"))
    assert saved != name, "a new upload must not take an archived file's name"
    assert (hot / saved).read_bytes() == b"another gel"


@pytest.mark.django_db
def test_a_new_file_never_lands_on_the_archive(archived):
    storage, name, content, hot, cold = archived
    saved = storage.save(name, ContentFile(b"new"))
    assert saved != name
    assert (hot / saved).exists()
    assert (cold / name).read_bytes() == content


@pytest.mark.django_db
def test_a_missing_file_that_was_never_archived_is_a_plain_not_found(tiers):
    with pytest.raises(FileNotFoundError) as excinfo:
        TieredMediaStorage().open("gel_images/originals/nope.tif")
    assert not isinstance(excinfo.value, ArchiveOfflineError)


@pytest.mark.django_db
def test_delete_removes_the_archived_copy(archived):
    storage, name, _content, _hot, cold = archived
    storage.delete(name)
    assert not (cold / name).exists()
    assert not ArchivedMediaFile.objects.exists()
    assert not storage.exists(name)


@pytest.mark.django_db
def test_delete_with_the_disk_away_is_settled_when_it_comes_back(archived):
    storage, name, _content, _hot, cold = archived
    unplug(cold)
    storage.delete(name)
    assert ArchivedMediaFile.objects.get(name=name).delete_pending
    assert (cold / name).exists()

    media_tiers.prepare_archive_root()  # the disk is back
    result = media_tiers.archive_pass()
    assert result["settled_deletes"] == 1
    assert not (cold / name).exists()
    assert not ArchivedMediaFile.objects.exists()


@pytest.mark.django_db
def test_restore_brings_a_file_back(archived, settings):
    storage, name, content, hot, cold = archived
    result = media_tiers.restore_files([name])
    assert result["restored_files"] == 1
    assert (hot / name).read_bytes() == content
    assert not (cold / name).exists()
    assert not ArchivedMediaFile.objects.exists()


@pytest.mark.django_db
def test_verify_reports_a_missing_and_a_damaged_file(archived):
    _storage, name, _content, _hot, cold = archived
    assert media_tiers.verify_archive(deep=True) == {"checked": 1, "missing": [], "corrupt": []}
    (cold / name).write_bytes(b"x" * 2000)
    assert media_tiers.verify_archive()["corrupt"] == [], "same size: only a deep check sees it"
    assert media_tiers.verify_archive(deep=True)["corrupt"] == [name]
    (cold / name).unlink()
    assert media_tiers.verify_archive()["missing"] == [name]


# ───────────── status + command ─────────────


@pytest.mark.django_db
def test_status_flags_archived_files_behind_an_unplugged_disk(archived):
    _storage, _name, _content, _hot, cold = archived
    status = media_tiers.storage_status(fresh=True)
    assert status["archive_state"] == "ready"
    assert (status["archived_files"], status["archived_bytes"]) == (1, 2000)
    assert not status["needs_attention"]
    unplug(cold)
    status = media_tiers.storage_status(fresh=True)
    assert status["needs_attention"] and status["archive_free_bytes"] is None


@pytest.mark.django_db
def test_command_status_archive_verify(tiers, capsys):
    hot, _cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    call_command("media_storage", "status")
    assert "OVER QUOTA" in capsys.readouterr().out
    call_command("media_storage", "archive")
    assert "Moved 1 file(s)" in capsys.readouterr().out
    call_command("media_storage", "verify", "--deep")
    assert "Archive matches its records" in capsys.readouterr().out
    call_command("media_storage", "restore", "--all")
    assert "Restored 1 file(s)" in capsys.readouterr().out


@pytest.mark.django_db
def test_command_refuses_cleanly_when_the_disk_is_away(tiers):
    _hot, cold = tiers
    unplug(cold)
    with pytest.raises(CommandError, match="archive not available"):
        call_command("media_storage", "verify")


def test_archive_task_is_scheduled_only_with_an_archive(settings):
    # Built at import from the environment: the test settings have no archive.
    assert "archive-media-nightly" not in settings.CELERY_BEAT_SCHEDULE


@pytest.mark.django_db
def test_archive_task_runs_a_pass(tiers):
    from phoresis_core.tasks import archive_media

    hot, cold = tiers
    put(hot, "gel_images/originals/2026/01/a.tif", 2000)
    assert archive_media.apply().get()["moved_files"] == 1
    assert (cold / "gel_images/originals/2026/01/a.tif").exists()


# ───────────── macOS privacy, health, serving ─────────────


def test_a_disk_macos_refuses_to_show_is_offline_with_the_way_out(tiers, monkeypatch):
    real_stat = os.stat

    def refusing_stat(path, *args, **kwargs):
        if media_tiers.MARKER_NAME in str(path):
            raise PermissionError(1, "Operation not permitted")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(media_tiers.os, "stat", refusing_stat)
    state = media_tiers.archive_state()
    assert state.state == media_tiers.OFFLINE
    assert "disk-access" in state.detail


@pytest.mark.django_db
def test_healthz_names_the_archive_only_where_there_is_one(client, tiers, settings):
    from unittest.mock import patch

    from django.urls import reverse

    _hot, cold = tiers
    with (
        patch("phoresis_core.healthz._celery_alive", return_value=True),
        patch("phoresis_core.healthz._redis_alive", return_value=True),
    ):
        assert client.get(reverse("healthz")).json()["subsystems"]["media_archive"] == "ready"
        unplug(cold)
        body = client.get(reverse("healthz"))
        assert body.status_code == 200, "the app is healthy without its archive disk"
        assert body.json()["subsystems"]["media_archive"] == "unprepared"
        settings.PHORESIS_MEDIA_ARCHIVE_ROOT = ""
        assert "media_archive" not in client.get(reverse("healthz")).json()["subsystems"]


@pytest.mark.django_db
def test_serve_media_reads_the_archive_for_signed_in_users(archived, rf, django_user_model):
    from django.contrib.auth.models import AnonymousUser
    from django.http import Http404

    _storage, name, content, _hot, cold = archived
    request = rf.get(f"/media/{name}")
    request.user = AnonymousUser()
    with pytest.raises(Http404):
        media_tiers.serve_media(request, name)

    request.user = django_user_model.objects.create_user(username="reader", password="x")
    response = media_tiers.serve_media(request, name)
    assert b"".join(response.streaming_content) == content
    with pytest.raises(Http404):
        media_tiers.serve_media(request, "gel_images/originals/nope.tif")
    with pytest.raises(Http404):
        media_tiers.serve_media(request, "../outside.txt")

    unplug(cold)
    response = media_tiers.serve_media(request, name)
    assert response.status_code == 503 and b"Reconnect the disk" in response.content
