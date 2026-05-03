"""Tests for gel_analyzer analysis views (Phase 3 shells)."""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory
from gel_analyzer.models import GelImage


@pytest.fixture
def gel_image(db):
    user = UserFactory(username="ga_user")
    return GelImage.objects.create(
        original_filename="x.png",
        file_format=GelImage.FileFormat.PNG,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=user,
    )


@pytest.mark.django_db
def test_analysis_list_returns_200(client, gel_image) -> None:
    user = UserFactory(username="al_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_list"))
    assert response.status_code == 200
    assert b"Analyses" in response.content


@pytest.mark.django_db
def test_analysis_create_get_returns_200(client, gel_image) -> None:
    user = UserFactory(username="ac_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image.pk}))
    assert response.status_code == 200
    assert b"New analysis" in response.content
