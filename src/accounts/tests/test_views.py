"""Integration tests for accounts views."""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_login_get_returns_200(client) -> None:
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_login_post_with_valid_creds_redirects_to_dashboard(client) -> None:
    """Will fail until Task 11 (`dashboard:home`) lands."""
    UserFactory(username="frank")
    response = client.post(
        reverse("accounts:login"),
        {"username": "frank", "password": "test-pwd"},
    )
    assert response.status_code == 302
    assert response.url == reverse("dashboard:home")


@pytest.mark.django_db
def test_login_post_with_bad_creds_returns_200_with_error(client) -> None:
    response = client.post(
        reverse("accounts:login"),
        {"username": "ghost", "password": "wrong"},
    )
    assert response.status_code == 200
    assert b"correct" in response.content.lower() or b"invalid" in response.content.lower()


@pytest.mark.django_db
def test_profile_requires_login(client) -> None:
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_profile_view_authenticated_returns_200(client) -> None:
    user = UserFactory(username="hank")
    client.force_login(user)
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_logout_redirects_to_login(client) -> None:
    user = UserFactory(username="iris")
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url
