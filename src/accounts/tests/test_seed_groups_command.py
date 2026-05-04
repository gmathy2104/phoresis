"""Tests for the seed_groups management command."""

import pytest

from django.contrib.auth.models import Group
from django.core.management import call_command

from accounts.permissions import ALL_GROUPS, GROUP_ADMIN, GROUP_LAB_USER, GROUP_REVIEWER


@pytest.mark.django_db
def test_seed_groups_command_creates_three_groups() -> None:
    Group.objects.all().delete()  # ensure clean slate
    call_command("seed_groups")
    names = set(Group.objects.values_list("name", flat=True))
    assert {GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN}.issubset(names)


@pytest.mark.django_db
def test_seed_groups_command_is_idempotent() -> None:
    call_command("seed_groups")
    count = Group.objects.filter(name__in=ALL_GROUPS).count()
    call_command("seed_groups")
    assert Group.objects.filter(name__in=ALL_GROUPS).count() == count
