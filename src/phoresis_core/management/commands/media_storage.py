"""Media on two disks: status, and the operator's actions on the archive (phoresis_core.media_tiers).

manage.py media_storage status [--json]
manage.py media_storage prepare               create the archive folder + marker (disk plugged in)
manage.py media_storage archive [--dry-run] [--gb N]
manage.py media_storage restore (--all | NAME ...)
manage.py media_storage verify [--deep]
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from phoresis_core import media_tiers


def human(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class Command(BaseCommand):
    help = "Media storage on two disks: status, prepare, archive, restore, verify"

    def add_arguments(self, parser) -> None:
        sub = parser.add_subparsers(dest="action", required=True)
        status = sub.add_parser("status")
        status.add_argument("--json", action="store_true")
        sub.add_parser("prepare")
        archive = sub.add_parser("archive")
        archive.add_argument("--dry-run", action="store_true", help="Say what would move, move nothing")
        archive.add_argument("--gb", type=float, help="Archive this much now, whatever the quota")
        restore = sub.add_parser("restore")
        restore.add_argument("names", nargs="*")
        restore.add_argument("--all", action="store_true")
        verify = sub.add_parser("verify")
        verify.add_argument("--deep", action="store_true", help="Also re-read every file and check its SHA-256")

    def handle(self, *args, **options) -> None:
        try:
            getattr(self, f"_{options['action']}")(options)
        except (media_tiers.ArchiveOfflineError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

    def _status(self, options) -> None:
        status = media_tiers.storage_status(fresh=True)
        if options["json"]:
            self.stdout.write(json.dumps(status, indent=2))
            return
        out = self.stdout.write
        out(f"Fast disk   {status['hot_root']}")
        if status["archive_state"] == media_tiers.DISABLED:
            out(f"  media     {human(status['hot_bytes'])}  (free on disk: {human(status['hot_free_bytes'])})")
            out("Archive     not configured (PHORESIS_MEDIA_ARCHIVE_ROOT unset): everything stays on the fast disk")
            return
        out(
            f"  media     {human(status['hot_bytes'])} of {human(status['hot_quota_bytes'])} quota"
            f" ({status['hot_quota_percent']} %)" + ("  OVER QUOTA" if status["over_quota"] else "")
        )
        out(
            f"  free      {human(status['hot_free_bytes'])} (floor {human(status['min_free_bytes'])})"
            + ("  LOW" if status["low_free_space"] else "")
        )
        out(f"Archive     {status['archive_root']}")
        out(
            f"  state     {status['archive_state']}"
            + (f": {status['archive_detail']}" if status["archive_detail"] else "")
        )
        if status["archive_free_bytes"] is not None:
            out(f"  free      {human(status['archive_free_bytes'])}")
        out(f"  archived  {status['archived_files']} file(s), {human(status['archived_bytes'])}")
        if status["pending_deletes"]:
            out(f"  pending   {status['pending_deletes']} deletion(s) waiting for the disk")

    def _prepare(self, options) -> None:
        root = media_tiers.prepare_archive_root()
        self.stdout.write(self.style.SUCCESS(f"Archive ready: {root}"))

    def _archive(self, options) -> None:
        force = int(options["gb"] * 1024**3) if options["gb"] is not None else None
        result = media_tiers.archive_pass(dry_run=options["dry_run"], force_bytes=force)
        verb = "Would move" if options["dry_run"] else "Moved"
        self.stdout.write(f"{verb} {result['moved_files']} file(s), {human(result['moved_bytes'])}")
        if result["settled_deletes"]:
            self.stdout.write(f"Removed {result['settled_deletes']} archived file(s) deleted while the disk was away")
        if result["reason"]:
            self.stdout.write(f"Note: {result['reason']}")

    def _restore(self, options) -> None:
        if not options["all"] and not options["names"]:
            raise CommandError("Give file names, or --all")
        result = media_tiers.restore_files(None if options["all"] else options["names"])
        self.stdout.write(f"Restored {result['restored_files']} file(s), {human(result['restored_bytes'])}")
        if result["failed"]:
            raise CommandError(f"{len(result['failed'])} file(s) not restored: " + ", ".join(result["failed"][:10]))

    def _verify(self, options) -> None:
        result = media_tiers.verify_archive(deep=options["deep"])
        self.stdout.write(f"Checked {result['checked']} file(s)")
        for label in ("missing", "corrupt"):
            for name in result[label]:
                self.stdout.write(self.style.ERROR(f"  {label}: {name}"))
        if result["missing"] or result["corrupt"]:
            raise CommandError("The archive does not match its records")
        self.stdout.write(self.style.SUCCESS("Archive matches its records"))
