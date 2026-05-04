"""Tests for accounts.signals."""

import pytest

from accounts.models import User, UserProfile


@pytest.mark.django_db
def test_user_profile_is_auto_created_on_user_creation() -> None:
    user = User.objects.create_user(username="dora", email="d@example.com", password="x")
    assert UserProfile.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_user_profile_is_not_recreated_on_save() -> None:
    user = User.objects.create_user(username="erin", email="e@example.com", password="x")
    user.first_name = "Erin"
    user.save()
    assert UserProfile.objects.filter(user=user).count() == 1
