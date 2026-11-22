"""Media on two disks: a fast one (MEDIA_ROOT) and an archive (PHORESIS_MEDIA_ARCHIVE_ROOT).

Why: on the Mac mini, gels accumulate for years on a small internal SSD while an external drive sits
next to it. Every upload is written to MEDIA_ROOT; once MEDIA_ROOT outgrows its quota (or its disk runs
short of free space), ``archive_pass`` moves the OLDEST archivable files to the archive disk. A file
keeps its name, so no row changes: ``TieredMediaStorage`` looks on the fast disk first, then on the
archive. Caddy does the same for ``/media/`` (scripts/mac/phoresis.sh).

Rules that keep the data safe:

- **Nothing is ever written to an archive that is not there.** The archive root must be prepared once
  by the operator (``manage.py media_storage prepare``), which drops a marker file in it. No marker
  (disk unplugged, wrong disk, folder never prepared) means *offline*: no archiving, and reading an
  archived file raises ``ArchiveOfflineError``. Under ``/Volumes`` the volume must also be a mount
  point: with the disk unplugged, the same path would otherwise land on the system disk.
- **Copy, check, then delete.** A file leaves the fast disk only after its copy was written under a
  temporary name, flushed to the disk, re-read and compared (SHA-256), renamed, and recorded in
  ``ArchivedMediaFile``. A crash at any point leaves at least one good copy.
- **A name on the archive stays taken**, disk connected or not (``exists``), so a new upload never
  gets the name of an archived file.

The archive is a second place, not a backup: an archived file exists ONLY on the archive disk.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.utils._os import safe_join

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

MARKER_NAME = ".phoresis-media-archive"
_CHUNK = 1024 * 1024
_LOCK_KEY = "phoresis:media_tiers:pass-running"
_HOT_USAGE_KEY = "phoresis:media_tiers:hot-usage"
# After a pass, the fast disk is brought this far UNDER its quota, so the next upload does not
# trigger another pass the following night.
_QUOTA_MARGIN = 0.10

DISABLED = "disabled"  # no archive configured (Windows / Docker)
READY = "ready"
OFFLINE = "offline"  # the disk is not connected
UNPREPARED = "unprepared"  # the disk is there, the folder or its marker is not


class ArchiveOfflineError(FileNotFoundError):
    """The file is on the archive disk, and the archive disk is not connected."""


@dataclass(frozen=True)
class ArchiveState:
    state: str
    root: Path | None = None
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.state == READY


def _volume_of(path: Path) -> Path | None:
    """``/Volumes/<name>`` for a path on a macOS external volume, else None."""
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        return Path("/Volumes") / parts[2]
    return None


def archive_state() -> ArchiveState:
    """Whether the archive can be read and written right now. Checked at every use: disks come and go."""
    configured = getattr(settings, "PHORESIS_MEDIA_ARCHIVE_ROOT", "")
    if not configured:
        return ArchiveState(DISABLED)
    root = Path(configured)
    volume = _volume_of(root)
    if volume is not None and not os.path.ismount(volume):
        return ArchiveState(OFFLINE, root, f"{volume} is not connected")
    try:
        # os.stat, not Path.is_dir(): a refusal must be told apart from an absence.
        os.stat(root / MARKER_NAME)
    except PermissionError:
        # macOS: a background service may not read an external disk until the operator allows it
        # (seen on a launchd agent: "Operation not permitted" on /Volumes/<disk>).
        return ArchiveState(
            OFFLINE,
            root,
            f"macOS denies access to {volume or root}: give Full Disk Access to Phoresis' Python "
            "(scripts/mac/phoresis.sh disk-access)",
        )
    except OSError:
        if volume is None and not root.parent.exists():
            return ArchiveState(OFFLINE, root, f"{root.parent} does not exist")
        what = f"has no {MARKER_NAME} marker" if root.is_dir() else "does not exist"
        return ArchiveState(UNPREPARED, root, f"{root} {what}: run `manage.py media_storage prepare`")
    return ArchiveState(READY, root)


def prepare_archive_root() -> Path:
    """Create the archive folder and its marker. An explicit operator action, never done implicitly."""
    configured = getattr(settings, "PHORESIS_MEDIA_ARCHIVE_ROOT", "")
    if not configured:
        raise ValueError("PHORESIS_MEDIA_ARCHIVE_ROOT is not set")
    root = Path(configured)
    volume = _volume_of(root)
    if volume is not None and not os.path.ismount(volume):
        raise ValueError(f"{volume} is not connected: plug the disk in first")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER_NAME
    if not marker.exists():
        marker.write_text(
            "Phoresis media archive. Files here exist nowhere else: do not delete or rename this folder.\n"
        )
    return root


def _record_model():
    from phoresis_core.models import ArchivedMediaFile

    return ArchivedMediaFile


class TieredMediaStorage(FileSystemStorage):
    """A FileSystemStorage whose files may have been moved, under the same name, to the archive root.

    ``path()`` answers where the file IS (fast disk first, then archive), so everything the base class
    builds on it (open, size, times) reads from the right place. New files are always written to the
    fast disk.
    """

    def hot_path(self, name: str) -> str:
        return super().path(name)

    def cold_path(self, name: str) -> str | None:
        """The file's place on the archive, or None while the archive is not ready."""
        state = archive_state()
        if not state.ready:
            return None
        return safe_join(str(state.root), name)

    def path(self, name: str) -> str:
        hot = self.hot_path(name)
        if os.path.lexists(hot):
            return hot
        cold = self.cold_path(name)
        if cold and os.path.lexists(cold):
            return cold
        return hot

    def _recorded(self, name: str) -> bool:
        return _record_model().objects.filter(name=name).exists()

    def exists(self, name: str) -> bool:
        if os.path.lexists(self.path(name)):
            return True
        # Archive not readable: the record alone says the name is taken.
        return not archive_state().ready and self._recorded(name)

    def _open(self, name, mode="rb"):
        if not os.path.lexists(self.path(name)) and self._recorded(name):
            state = archive_state()
            raise ArchiveOfflineError(
                f"{name} is on the media archive disk ({state.root}), which is not available: "
                f"{state.detail or 'file missing from the archive'}. Reconnect the disk and retry."
            )
        return super()._open(name, mode)

    def _save(self, name, content):
        # Never write through path() onto the archive: a name that only lives there is taken.
        while not os.path.lexists(self.hot_path(name)) and self.exists(name):
            name = self.get_available_name(name)
        return super()._save(name, content)

    def delete(self, name: str) -> None:
        if not name:
            raise ValueError("The name must be given to delete().")
        hot = self.hot_path(name)
        if os.path.lexists(hot):
            os.remove(hot)
        records = _record_model().objects.filter(name=name)
        cold = self.cold_path(name)
        if cold is not None:
            if os.path.lexists(cold):
                os.remove(cold)
            records.delete()
        else:
            # Disk unplugged: the archived copy is removed by the next pass that finds the disk.
            records.update(delete_pending=True)
        cache.delete(_HOT_USAGE_KEY)


# ───────────────────────── measuring ─────────────────────────


def _walk_files(root: Path):
    """(relative name, size, mtime) of every regular file under ``root``; partial copies skipped."""
    if not root.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename.startswith(".") or filename.endswith(".part"):
                continue
            full = os.path.join(dirpath, filename)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            yield os.path.relpath(full, root).replace(os.sep, "/"), st.st_size, st.st_mtime


def hot_usage_bytes(*, fresh: bool = False) -> int:
    """Size of everything under MEDIA_ROOT. A directory walk, so cached ten minutes for the dashboard."""
    if not fresh:
        cached = cache.get(_HOT_USAGE_KEY)
        if cached is not None:
            return cached
    total = sum(size for _name, size, _mtime in _walk_files(Path(settings.MEDIA_ROOT)))
    cache.set(_HOT_USAGE_KEY, total, 600)
    return total


def _free_bytes(path: Path) -> int | None:
    """Free space on the disk holding ``path`` (its nearest existing parent), None if unreadable."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            try:
                return shutil.disk_usage(candidate).free
            except OSError:
                return None
    return None


def storage_status(*, fresh: bool = False) -> dict:
    """Everything the command and the dashboard card show. Sizes in bytes."""
    from django.db.models import Count, Sum

    hot_root = Path(settings.MEDIA_ROOT)
    hot_bytes = hot_usage_bytes(fresh=fresh)
    hot_free = _free_bytes(hot_root)
    state = archive_state()
    status = {
        "hot_root": str(hot_root),
        "hot_bytes": hot_bytes,
        "hot_free_bytes": hot_free,
        "archive_state": state.state,
        "archive_root": str(state.root) if state.root else "",
        "archive_detail": state.detail,
    }
    if state.state == DISABLED:
        return status
    quota = settings.PHORESIS_MEDIA_HOT_QUOTA_BYTES
    min_free = settings.PHORESIS_MEDIA_MIN_FREE_BYTES
    records = _record_model().objects
    archived = records.filter(delete_pending=False).aggregate(n=Count("id"), size=Sum("size_bytes"))
    status.update(
        hot_quota_bytes=quota,
        hot_quota_percent=min(100, round(100 * hot_bytes / quota)) if quota else 0,
        min_free_bytes=min_free,
        over_quota=hot_bytes > quota,
        low_free_space=hot_free is not None and hot_free < min_free,
        archive_free_bytes=_free_bytes(state.root) if state.ready else None,
        archived_files=archived["n"] or 0,
        archived_bytes=archived["size"] or 0,
        pending_deletes=records.filter(delete_pending=True).count(),
    )
    status["needs_attention"] = (status["over_quota"] or status["low_free_space"] or status["archived_files"] > 0) and (
        not state.ready
    )
    return status


# ───────────────────────── moving ─────────────────────────


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _flush_to_disk(fh) -> None:
    fh.flush()
    try:
        import fcntl

        # macOS: fsync() stops at the drive's cache; F_FULLFSYNC waits for the platters.
        fcntl.fcntl(fh.fileno(), fcntl.F_FULLFSYNC)
    except (ImportError, AttributeError, OSError):
        os.fsync(fh.fileno())


def _copy_checked(src: str, dst: str) -> tuple[int, str]:
    """Copy ``src`` to ``dst`` through a temporary name; returns (size, sha256) once both ends agree."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = os.path.join(os.path.dirname(dst), f".{os.path.basename(dst)}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            while chunk := fin.read(_CHUNK):
                digest.update(chunk)
                fout.write(chunk)
                size += len(chunk)
            _flush_to_disk(fout)
        expected = digest.hexdigest()
        if os.path.getsize(tmp) != size or _sha256(tmp) != expected:
            raise OSError(f"copy of {src} does not match its source")
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return size, expected


def _settle_pending_deletes(root: Path) -> int:
    """Remove the archived copy of files deleted while the disk was unplugged."""
    settled = 0
    records = _record_model().objects
    for record in records.filter(delete_pending=True):
        cold = safe_join(str(root), record.name)
        try:
            if os.path.lexists(cold):
                os.remove(cold)
            record.delete()
            settled += 1
        except OSError as exc:
            logger.warning(f"media archive: could not remove {record.name}: {exc}")
    return settled


def _candidates(hot_root: Path, min_age_days: int) -> list[tuple[str, int, float]]:
    """Archivable files, in the order they leave: prefix order, then oldest first."""
    cutoff = time.time() - min_age_days * 86400
    ordered: list[tuple[str, int, float]] = []
    for prefix in settings.PHORESIS_MEDIA_ARCHIVE_PREFIXES:
        base = hot_root / prefix
        found = [
            (f"{prefix.rstrip('/')}/{name}", size, mtime) for name, size, mtime in _walk_files(base) if mtime <= cutoff
        ]
        ordered.extend(sorted(found, key=lambda item: item[2]))
    return ordered


def archive_pass(*, time_budget_s: float = 1200, dry_run: bool = False, force_bytes: int | None = None) -> dict:
    """Move the oldest archivable files to the archive until MEDIA_ROOT is back under its quota.

    ``force_bytes`` archives that much regardless of the quota (operator request). Returns a summary;
    ``result["reason"]`` says why nothing (or not enough) moved.
    """
    result = {"moved_files": 0, "moved_bytes": 0, "settled_deletes": 0, "still_needed_bytes": 0, "reason": ""}
    state = archive_state()
    if state.state == DISABLED:
        result["reason"] = "no archive configured"
        return result
    if not state.ready:
        result["reason"] = f"archive not available: {state.detail}"
        logger.warning(f"media archive: {result['reason']}")
        return result
    if not dry_run and not cache.add(_LOCK_KEY, 1, timeout=int(time_budget_s) + 600):
        result["reason"] = "another pass is running"
        return result
    try:
        return _archive_pass_locked(state.root, result, time_budget_s, dry_run, force_bytes)
    finally:
        if not dry_run:
            cache.delete(_LOCK_KEY)
            cache.delete(_HOT_USAGE_KEY)


def _archive_pass_locked(root: Path, result: dict, time_budget_s: float, dry_run: bool, force_bytes) -> dict:
    hot_root = Path(settings.MEDIA_ROOT)
    storage = TieredMediaStorage()
    records = _record_model().objects
    if not dry_run:
        result["settled_deletes"] = _settle_pending_deletes(root)

    quota = settings.PHORESIS_MEDIA_HOT_QUOTA_BYTES
    hot_bytes = hot_usage_bytes(fresh=True)
    hot_free = _free_bytes(hot_root)
    over_quota = hot_bytes - quota
    under_floor = settings.PHORESIS_MEDIA_MIN_FREE_BYTES - hot_free if hot_free is not None else 0
    if force_bytes is not None:
        needed = force_bytes
    elif over_quota > 0 or under_floor > 0:
        needed = max(over_quota + int(quota * _QUOTA_MARGIN), under_floor)
    else:
        needed = 0
    if needed <= 0:
        result["reason"] = "under quota"
        return result

    deadline = time.monotonic() + time_budget_s
    archive_floor = settings.PHORESIS_MEDIA_ARCHIVE_MIN_FREE_BYTES
    for name, size, _mtime in _candidates(hot_root, settings.PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS):
        if result["moved_bytes"] >= needed:
            break
        if time.monotonic() > deadline:
            result["reason"] = "time budget reached, continues at the next pass"
            break
        archive_free = _free_bytes(root)
        if archive_free is not None and archive_free - size < archive_floor:
            result["reason"] = "archive disk is full"
            break
        if dry_run:
            result["moved_files"] += 1
            result["moved_bytes"] += size
            continue
        hot, cold = storage.hot_path(name), safe_join(str(root), name)
        try:
            copied_size, sha256 = _copy_checked(hot, cold)
            records.update_or_create(
                name=name, defaults={"size_bytes": copied_size, "sha256": sha256, "delete_pending": False}
            )
            os.remove(hot)
        except OSError as exc:
            # One unreadable file, or the disk pulled mid-pass: stop here, everything moved so far is safe.
            logger.error(f"media archive: {name} not archived: {exc}")
            result["reason"] = f"stopped on {name}: {exc}"
            break
        result["moved_files"] += 1
        result["moved_bytes"] += size

    result["still_needed_bytes"] = max(0, needed - result["moved_bytes"])
    if result["still_needed_bytes"] and not result["reason"]:
        result["reason"] = (
            f"nothing older than {settings.PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS} days left to archive: "
            "raise the quota or lower PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS"
        )
    verb = "would move" if dry_run else "moved"
    logger.info(
        f"media archive: {verb} {result['moved_files']} file(s), {result['moved_bytes']} bytes"
        + (f" ({result['reason']})" if result["reason"] else "")
    )
    return result


def restore_files(names: list[str] | None = None) -> dict:
    """Bring archived files back to the fast disk: the given names, or all of them."""
    result = {"restored_files": 0, "restored_bytes": 0, "failed": []}
    state = archive_state()
    if not state.ready:
        raise ArchiveOfflineError(f"archive not available: {state.detail or state.state}")
    storage = TieredMediaStorage()
    records = _record_model().objects.filter(delete_pending=False)
    if names is not None:
        records = records.filter(name__in=names)
    for record in records.order_by("name"):
        cold, hot = safe_join(str(state.root), record.name), storage.hot_path(record.name)
        try:
            if not os.path.lexists(hot):
                _copy_checked(cold, hot)
            if os.path.lexists(cold):
                os.remove(cold)
            record.delete()
        except OSError as exc:
            logger.error(f"media archive: {record.name} not restored: {exc}")
            result["failed"].append(record.name)
            continue
        result["restored_files"] += 1
        result["restored_bytes"] += record.size_bytes
    cache.delete(_HOT_USAGE_KEY)
    return result


def verify_archive(*, deep: bool = False) -> dict:
    """Check every recorded file is on the archive with its recorded size (``deep``: and its SHA-256)."""
    state = archive_state()
    if not state.ready:
        raise ArchiveOfflineError(f"archive not available: {state.detail or state.state}")
    result = {"checked": 0, "missing": [], "corrupt": []}
    for record in _record_model().objects.filter(delete_pending=False).order_by("name"):
        cold = safe_join(str(state.root), record.name)
        result["checked"] += 1
        if not os.path.isfile(cold):
            # Still on the fast disk (a pass interrupted before the delete) is not a loss.
            if not os.path.isfile(TieredMediaStorage().hot_path(record.name)):
                result["missing"].append(record.name)
        elif os.path.getsize(cold) != record.size_bytes or (deep and _sha256(cold) != record.sha256):
            result["corrupt"].append(record.name)
    return result


# ───────────────────────── serving ─────────────────────────


def serve_media(request, name: str):
    """``/media/<name>`` for a file the web server did not find on the fast disk: the archive's copy.

    Caddy serves what is on the fast disk itself and forwards the rest here (scripts/mac/phoresis.sh),
    so that Django's Python is the only program needing macOS' permission to read the external disk.
    Signed-in users only: an archived original is a download, not a page asset.
    """
    from django.core.exceptions import SuspiciousFileOperation
    from django.http import FileResponse, Http404, HttpResponse

    if not request.user.is_authenticated:
        raise Http404
    try:
        handle = TieredMediaStorage().open(name, "rb")
    except ArchiveOfflineError as exc:
        return HttpResponse(str(exc), status=503, content_type="text/plain; charset=utf-8")
    except (FileNotFoundError, IsADirectoryError, SuspiciousFileOperation):
        raise Http404 from None
    return FileResponse(handle)
