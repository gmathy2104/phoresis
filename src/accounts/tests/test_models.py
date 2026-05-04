"""Tests for the accounts.User and accounts.UserProfile models."""

import pytest

from accounts.models import User, UserProfile


@pytest.mark.django_db
def test_user_can_be_created_with_email_and_password() -> None:
    user = User.objects.create_user(username="alice", email="alice@example.com", password="pwd12345")
    assert user.username == "alice"
    assert user.email == "alice@example.com"
    assert user.check_password("pwd12345")


@pytest.mark.django_db
def test_user_profile_default_theme_is_auto() -> None:
    user = User.objects.create_user(username="bob", email="bob@example.com", password="pwd12345")
    profile = user.profile  # OneToOne reverse accessor
    assert profile.theme == UserProfile.THEME_AUTO
    assert profile.language == UserProfile.LANG_EN


@pytest.mark.django_db
def test_user_str_uses_full_name_when_available() -> None:
    user = User.objects.create_user(
        username="carol", email="c@example.com", password="x", first_name="Carol", last_name="Danvers"
    )
    assert str(user) == "Carol Danvers"


@pytest.mark.django_db
def test_user_str_falls_back_to_username() -> None:
    user = User.objects.create_user(username="lone", email="l@example.com", password="x")
    assert str(user) == "lone"
