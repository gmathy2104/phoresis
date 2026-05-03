"""Tests for the 0002_seed_groups data migration."""

import pytest

from django.contrib.auth.models import Group

from accounts.permissions import GROUP_ADMIN, GROUP_LAB_USER, GROUP_REVIEWER


@pytest.mark.django_db
def test_three_groups_are_seeded() -> None:
    names = set(Group.objects.values_list("name", flat=True))
    assert {GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN}.issubset(names)
