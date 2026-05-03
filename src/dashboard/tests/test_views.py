"""Tests for the dashboard home view."""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_home_redirects_anonymous_to_login(client) -> None:
    response = client.get(reverse("dashboard:home"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_home_returns_200_for_authenticated_user(client) -> None:
    user = UserFactory(username="jay")
    client.force_login(user)
    response = client.get(reverse("dashboard:home"))
    assert response.status_code == 200
    assert b"Phoresis" in response.content
    assert b"Welcome back" in response.content


@pytest.mark.django_db
def test_home_renders_kpis(client) -> None:
    user = UserFactory(username="kayla")
    client.force_login(user)
    response = client.get(reverse("dashboard:home"))
    assert b"Total gels" in response.content
    assert b"Total analyses" in response.content
