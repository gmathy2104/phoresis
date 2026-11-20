"""The gel dashboard: what its picker offers, and the page itself."""

import json

import pytest

from django.urls import reverse

from gel_analyzer.models import GelAnalysis, GelImage, Lane, LaneDensitometrySummary
from gel_analyzer.views.dashboard import MAX_LANES, pickable_gels


def _analysed(lane, poi_percentage=80.0):
    return LaneDensitometrySummary.objects.create(
        lane=lane, total_integrated_area=1000.0, band_count=2, poi_band_count=1, poi_percentage=poi_percentage
    )


@pytest.mark.django_db
def test_picker_lists_a_gel_once_a_lane_is_analysed_and_only_that_lane_can_be_ticked(
    gel_analysis, sample_lane, ladder_lane
):
    assert pickable_gels() == []  # no densitometry yet: nothing to show

    _analysed(sample_lane, poi_percentage=72.44)
    (gel,) = pickable_gels()

    assert gel["id"] == str(gel_analysis.pk)
    assert gel["filename"] == gel_analysis.gel_image.original_filename
    by_id = {lane["id"]: lane for lane in gel["lanes"]}
    assert by_id[sample_lane.pk]["analysed"] is True
    assert by_id[ladder_lane.pk]["analysed"] is False  # listed, greyed by the page


@pytest.mark.django_db
def test_picker_gives_a_purity_only_where_the_gel_measures_one_and_a_poi_carries_signal(gel_analysis, sample_lane):
    image = gel_analysis.gel_image
    image.gel_type = GelImage.GelType.SDS_PAGE
    image.save(update_fields=["gel_type"])
    summary = _analysed(sample_lane, poi_percentage=72.44)

    assert pickable_gels()[0]["lanes"][0]["purity"] == 72.4

    # No POI band with signal: no purity, never a 0 % (signals.published_purity).
    summary.poi_percentage = 0
    summary.save(update_fields=["poi_percentage"])
    assert pickable_gels()[0]["lanes"][0]["purity"] is None

    # A western blot's POI share is not a purity.
    summary.poi_percentage = 95.0
    summary.save(update_fields=["poi_percentage"])
    image.gel_type = GelImage.GelType.WESTERN_BLOT
    image.save(update_fields=["gel_type"])
    assert pickable_gels()[0]["lanes"][0]["purity"] is None


@pytest.mark.django_db
def test_picker_leaves_out_a_rejected_analysis(gel_analysis, sample_lane):
    _analysed(sample_lane)
    gel_analysis.status = GelAnalysis.Status.REJECTED
    gel_analysis.save(update_fields=["status"])

    assert pickable_gels() == []


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("gel_analyzer:gel_dashboard"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard_page_carries_the_gels_and_the_lanes_asked_in_the_url(client, test_user, gel_analysis, sample_lane):
    _analysed(sample_lane)
    client.force_login(test_user)

    response = client.get(reverse("gel_analyzer:gel_dashboard"), {"lanes": f"{sample_lane.pk},abc,{sample_lane.pk},7"})

    assert response.status_code == 200
    assert json.loads(str(response.context["gels_json"]))[0]["id"] == str(gel_analysis.pk)
    # Garbage dropped, duplicates dropped, order kept.
    assert json.loads(str(response.context["selected_json"])) == [sample_lane.pk, 7]
    page = response.content.decode()
    assert "GelAnalyzer.Viz.GelDashboard.init" in page and 'id="gd-comparison"' in page


@pytest.mark.django_db
def test_dashboard_never_asks_for_more_lanes_than_the_component_draws(client, test_user):
    client.force_login(test_user)
    ids = ",".join(str(n) for n in range(1, MAX_LANES + 15))

    response = client.get(reverse("gel_analyzer:gel_dashboard"), {"lanes": ids})

    assert len(json.loads(str(response.context["selected_json"]))) == MAX_LANES


@pytest.mark.django_db
def test_a_sample_name_cannot_close_the_script_block(client, test_user, gel_analysis, sample_lane):
    _analysed(sample_lane)
    Lane.objects.filter(pk=sample_lane.pk).update(sample_name="</script><img src=x onerror=alert(1)>")
    client.force_login(test_user)

    page = client.get(reverse("gel_analyzer:gel_dashboard")).content.decode()

    assert "</script><img src=x" not in page
