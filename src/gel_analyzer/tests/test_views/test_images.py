"""Tests for gel_analyzer image views (Phase 3 shell pages)."""

import pytest

from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_image_list_requires_login(client) -> None:
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_image_list_authenticated_returns_200(client) -> None:
    user = UserFactory(username="img_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 200
    assert b"Gel images" in response.content


@pytest.mark.django_db
def test_image_upload_get_returns_200(client) -> None:
    user = UserFactory(username="up_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_upload"))
    assert response.status_code == 200
    assert b"Upload gel" in response.content


@pytest.mark.django_db
def test_upload_page_offers_the_assays_and_an_empty_gel_type(client) -> None:
    """The upload form requires an assay: a page without the select refuses every upload."""
    client.force_login(UserFactory(username="assay_up_user"))
    response = client.get(reverse("gel_analyzer:image_upload"))
    page = response.content.decode()
    assert 'name="assay"' in page and "Western blot — anti-HCP" in page
    # Empty, never the model default UNKNOWN: an empty gel type is taken from the assay.
    assert not response.context["form"]["gel_type"].value()


@pytest.mark.django_db
def test_upload_stores_the_assay_and_takes_its_gel_type(client, uploaded_gel_file) -> None:
    from gel_analyzer.models import GelAssay, GelImage

    client.force_login(UserFactory(username="assay_post_user"))
    assay = GelAssay.objects.get(name="SDS-PAGE")
    response = client.post(
        reverse("gel_analyzer:image_upload"),
        {"original_file": uploaded_gel_file, "assay": assay.pk, "gel_type": "", "description": ""},
    )
    assert response.status_code == 302
    image = GelImage.objects.get()
    assert (image.assay_id, image.gel_type) == (assay.pk, GelImage.GelType.SDS_PAGE)


@pytest.mark.django_db
def test_upload_without_an_assay_is_refused_with_the_reason_on_the_page(client, uploaded_gel_file) -> None:
    from gel_analyzer.models import GelImage

    client.force_login(UserFactory(username="no_assay_user"))
    response = client.post(
        reverse("gel_analyzer:image_upload"),
        {"original_file": uploaded_gel_file, "assay": "", "gel_type": "SDS_PAGE", "description": ""},
    )
    assert response.status_code == 200
    assert not GelImage.objects.exists()
    assert "This field is required" in response.content.decode()


@pytest.mark.django_db
def test_edit_page_changes_the_assay_and_refuses_one_of_another_gel_type(client, gel_image) -> None:
    from gel_analyzer.models import GelAssay, GelImage

    client.force_login(UserFactory(username="edit_user"))
    url = reverse("gel_analyzer:image_edit", kwargs={"pk": gel_image.pk})
    assert client.get(url).status_code == 200

    gel_image.gel_type = GelImage.GelType.SDS_PAGE
    gel_image.save(update_fields=["gel_type"])
    purity = GelAssay.objects.get(name="SDS-PAGE")
    response = client.post(url, {"assay": purity.pk, "gel_type": "SDS_PAGE", "description": "note"})
    assert response.status_code == 302
    gel_image.refresh_from_db()
    assert (gel_image.assay_id, gel_image.description) == (purity.pk, "note")

    western = GelAssay.objects.get(name="Western blot — anti-HCP")
    response = client.post(url, {"assay": western.pk, "gel_type": "SDS_PAGE", "description": "note"})
    assert response.status_code == 200
    gel_image.refresh_from_db()
    assert gel_image.assay_id == purity.pk
    assert "This assay is for Western Blot gels." in response.content.decode()


@pytest.mark.django_db
def test_image_list_filters_by_assay_and_keeps_the_filter_in_its_chips(client, gel_image) -> None:
    from gel_analyzer.models import GelAssay, GelImage

    client.force_login(UserFactory(username="filter_user"))
    western = GelAssay.objects.get(name="Western blot — anti-HCP")
    blot = GelImage.objects.create(
        original_file="b.png", original_filename="blot.png", gel_type=GelImage.GelType.WESTERN_BLOT, assay=western
    )

    response = client.get(reverse("gel_analyzer:image_list"), {"assay": western.pk})

    assert [image.pk for image in response.context["images"]] == [blot.pk]
    page = response.content.decode()
    # The ticked value is a form input (submitting another filter keeps it), and a chip removes it.
    assert f'name="assay" value="{western.pk}" checked' in page
    assert "Assay: Western blot — anti-HCP" in page

    # An image without an assay is reached by the "No assay" option.
    response = client.get(reverse("gel_analyzer:image_list"), {"assay": "none"})
    assert [image.pk for image in response.context["images"]] == [gel_image.pk]


@pytest.mark.django_db
def test_image_page_shows_the_assay_and_the_lane_count(client, gel_image) -> None:
    client.force_login(UserFactory(username="detail_user"))
    page = client.get(reverse("gel_analyzer:image_detail", kwargs={"pk": gel_image.pk})).content.decode()
    assert "None — read from its gel type" in page and "Lanes" in page
