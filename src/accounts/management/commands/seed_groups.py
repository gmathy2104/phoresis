"""Idempotent seed for the three Phoresis groups.

Phase 1's data migration `0002_seed_groups` already creates the rows on
fresh databases; this command makes the contract explicit in scripted
contexts (entrypoint.sh, install.ps1) and lets operators re-seed after
manual cleanup without re-running migrations.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.permissions import ALL_GROUPS


class Command(BaseCommand):
    help = "Create the three Phoresis groups (Lab User, Reviewer, Admin) — idempotent."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for name in ALL_GROUPS:
            _, created = Group.objects.get_or_create(name=name)
            verb = "created" if created else "exists"
            self.stdout.write(f"  {name}: {verb}")
        self.stdout.write(self.style.SUCCESS(f"{len(ALL_GROUPS)} groups ready"))
