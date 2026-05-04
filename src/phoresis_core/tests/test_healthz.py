"""Tests for the /healthz/ endpoints."""

from unittest.mock import patch

import pytest

from django.urls import reverse


@pytest.mark.django_db
def test_healthz_returns_200_when_all_subsystems_ok(client) -> None:
    """When DB + Redis + Celery all respond, /healthz/ returns 200."""
    with (
        patch("phoresis_core.healthz._celery_alive", return_value=True),
        patch("phoresis_core.healthz._redis_alive", return_value=True),
    ):
        response = client.get(reverse("healthz"))
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "ok"
    assert body["subsystems"]["db"] == "ok"
    assert body["subsystems"]["redis"] == "ok"
    assert body["subsystems"]["celery"] == "ok"


@pytest.mark.django_db
def test_healthz_returns_503_when_redis_down(client) -> None:
    with (
        patch("phoresis_core.healthz._celery_alive", return_value=True),
        patch("phoresis_core.healthz._redis_alive", return_value=False),
    ):
        response = client.get(reverse("healthz"))
    assert response.status_code == 503
    assert response.json()["overall"] == "error"


@pytest.mark.django_db
def test_healthz_celery_only_returns_200_when_workers_alive(client) -> None:
    with patch("phoresis_core.healthz._celery_alive", return_value=True):
        response = client.get(reverse("healthz_celery"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_healthz_celery_only_returns_503_when_no_workers(client) -> None:
    with patch("phoresis_core.healthz._celery_alive", return_value=False):
        response = client.get(reverse("healthz_celery"))
    assert response.status_code == 503
