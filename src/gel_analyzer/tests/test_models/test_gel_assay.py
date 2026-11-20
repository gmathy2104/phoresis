"""GelAssay / GelImage pairing rules: a blot never ends up on a purity assay."""

import pytest

from django.core.exceptions import ValidationError

from gel_analyzer.models import GelAssay, GelImage

SDS = GelImage.GelType.SDS_PAGE
WB = GelImage.GelType.WESTERN_BLOT


@pytest.mark.django_db
def test_no_blot_can_end_up_on_a_purity_assay(gel_image):
    """Production, 2026-10: a western's POI share written as purity hid the SDS-PAGE value of 162
    samples. Three ways a western image could reach a PURITY readout, each refused."""
    # (a) a purity assay declared on a blot
    with pytest.raises(ValidationError) as exc:
        GelAssay(name="Blot purity", gel_type=WB, readout=GelAssay.Readout.PURITY).clean()
    assert "readout" in exc.value.message_dict

    # (b) an assay already used by an image changing gel type under it
    sds_only = GelAssay.objects.create(name="Test SDS, no readout", gel_type=SDS, readout=GelAssay.Readout.NONE)
    gel_image.assay = sds_only
    gel_image.save(update_fields=["assay"])
    sds_only.gel_type = WB
    with pytest.raises(ValidationError) as exc:
        sds_only.clean()
    assert "gel_type" in exc.value.message_dict

    # (c) an SDS-PAGE image put on a western assay
    western = GelAssay.objects.create(name="Test WB anti-HCP", gel_type=WB, readout=GelAssay.Readout.HOST_CELL_PROTEINS)
    gel_image.assay = western
    with pytest.raises(ValidationError) as exc:
        gel_image.clean()
    assert "assay" in exc.value.message_dict
