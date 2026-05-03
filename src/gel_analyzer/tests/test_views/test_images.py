"""Tests for gel_analyzer image views (Phase 3 shell pages).

Marked xfail(strict=False) until Task 14 wires the URLs. Once wired they pass.
"""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.xfail(strict=False, reason="URL wired in Task 14")
@pytest.mark.django_db
def test_image_list_requires_login(client) -> None:
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.xfail(strict=False, reason="URL wired in Task 14")
@pytest.mark.django_db
def test_image_list_authenticated_returns_200(client) -> None:
    user = UserFactory(username="img_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 200
    assert b"Gel images" in response.content


@pytest.mark.xfail(strict=False, reason="URL wired in Task 14")
@pytest.mark.django_db
def test_image_upload_get_returns_200(client) -> None:
    user = UserFactory(username="up_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_upload"))
    assert response.status_code == 200
    assert b"Upload gel" in response.content
