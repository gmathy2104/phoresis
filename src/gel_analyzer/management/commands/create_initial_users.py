"""Create initial Phoresis users from environment variables.

Idempotent: re-running with the same env vars won't create duplicate users
or raise. Used by `docker/entrypoint.sh` (Phase 5) to bring up the admin
and primary lab user on first container start.

Env vars consumed:
  ADMIN_EMAIL, ADMIN_PASSWORD          -> superuser, Admin group
  PRIMARY_USER_EMAIL, PRIMARY_USER_PASSWORD, PRIMARY_USER_FULL_NAME
                                       -> Lab User group, non-superuser

Usage:
    python manage.py create_initial_users --from-env
    python manage.py create_initial_users --from-env --skip-existing
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Create initial Phoresis users (admin + primary lab user) from .env"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--from-env",
            action="store_true",
            help="Read user data from environment variables (default: error out without it)",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip users that already exist by email instead of raising",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if not options["from_env"]:
            self.stderr.write(self.style.ERROR("--from-env is required (interactive mode not supported)."))
            return

        skip_existing = options["skip_existing"]
        User = get_user_model()

        # --- admin / superuser ---
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
        admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
        if admin_email and admin_password:
            self._create_user(
                User,
                username=admin_email.split("@")[0],
                email=admin_email,
                password=admin_password,
                full_name="Phoresis Admin",
                group_name="Admin",
                is_superuser=True,
                is_staff=True,
                skip_existing=skip_existing,
            )
        else:
            self.stdout.write("ADMIN_EMAIL / ADMIN_PASSWORD not set — skipping admin seed")

        # --- primary lab user ---
        primary_email = os.environ.get("PRIMARY_USER_EMAIL", "").strip()
        primary_password = os.environ.get("PRIMARY_USER_PASSWORD", "").strip()
        primary_full_name = os.environ.get("PRIMARY_USER_FULL_NAME", "Lab User").strip()
        if primary_email and primary_password:
            self._create_user(
                User,
                username=primary_email.split("@")[0],
                email=primary_email,
                password=primary_password,
                full_name=primary_full_name,
                group_name="Lab User",
                is_superuser=False,
                is_staff=False,
                skip_existing=skip_existing,
            )
        else:
            self.stdout.write("PRIMARY_USER_EMAIL / PRIMARY_USER_PASSWORD not set — skipping primary user seed")

    def _create_user(
        self,
        User,
        *,
        username: str,
        email: str,
        password: str,
        full_name: str,
        group_name: str,
        is_superuser: bool,
        is_staff: bool,
        skip_existing: bool,
    ) -> None:
        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            if skip_existing:
                self.stdout.write(f"User {email} already exists — skipped")
                return
            self.stdout.write(self.style.WARNING(f"User {email} already exists — updating password & group"))
            user = existing
            user.set_password(password)
        else:
            user = User(username=username, email=email)
            user.set_password(password)

        first_name, _, last_name = full_name.partition(" ")
        user.first_name = first_name
        user.last_name = last_name
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.save()

        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"User {email} ready (group={group_name})"))
