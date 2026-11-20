"""Mecanisme A -- une FK null=True sans blank=True bloque le re-enregistrement
d'une LadderCalibration existante depuis l'admin reel.

CE QUE CE FICHIER PROUVE, ET POURQUOI CE MODELE
-------------------------------------------------
Audit d'acces du 2026-08-28 (docs/reviews/2026-08-28-audit-acces-volet-decisionnel.md
§4.3bis) : sur les 12 champs mesures a risque, le mecanisme A (FK/O2O null=True
declaree SANS blank=True) touche 6 champs dans gel_analyzer. LadderCalibration.template
est le cas dominant du lot -- la majorite des calibrations existantes n'ont pas (ou
plus, apres suppression du template -> SET_NULL) de template rattache, un etat
legitime que le formulaire refusait comme "This field is required".

C'est aussi le seul des six champs gel_analyzer dont l'admin est REELLEMENT
enregistre et non neutralise (contrairement a MultiLadderCalibrationConfig et
ProteinQuantCalibrationPoint, qui n'ont aucun ModelAdmin aujourd'hui, ou a
SavedComparison.lanes, neutralise par Django via son through=). Ce test instancie
donc le vrai LadderCalibrationAdmin, pas un ModelForm generique.

ladder_lane est corrige par le meme geste (meme mecanisme, meme migration) et
laisse volontairement vide ici aussi -- inutile de le dupliquer dans un fichier
a part pour prouver le meme mecanisme deux fois.
"""

import json

import pytest

from django.contrib import admin
from django.test import RequestFactory

from gel_analyzer.admin import LadderCalibrationAdmin
from gel_analyzer.models import LadderCalibration


@pytest.mark.django_db
def test_ladder_calibration_without_template_or_ladder_lane_can_be_resaved(gel_analysis, test_user):
    """Rouvrir une calibration sans template ni ladder_lane et l'enregistrer sans
    y toucher doit marcher. Avant blank=True, ce geste repondait "This field is
    required" sur template (et ladder_lane) -- des champs que personne n'avait
    vides volontairement, juste jamais (ou plus) renseignes.
    """
    calib = LadderCalibration.objects.create(
        analysis=gel_analysis,
        ladder_lane=None,
        template=None,
        r_squared=0.99,
        matched_band_count=5,
        # created_by est hors perimetre de ce correctif (0 ligne bloquee mesuree) --
        # on le renseigne pour isoler le test au mecanisme sous test.
        created_by=test_user,
        # coefficients/band_matches non vides : ce sont aussi des JSONField sans
        # blank=True (hors perimetre, 0 ligne bloquee mesuree -- une calibration
        # reelle a toujours une courbe ajustee). Un JSON "{}" / "[]" est traite
        # comme vide par le champ required du formulaire ; les laisser a leur
        # defaut aurait fait echouer ce test pour une raison HORS mecanisme A.
        coefficients={"slope": 1.0, "intercept": 2.0},
        band_matches=[{"band_id": "x", "mw_kda": 10}],
    )

    # Superuser: Django admin's get_form() silently excludes EVERY field from a
    # change form when the requesting user fails has_change_permission -- an
    # empty field set trivially passes is_valid(), which would make this test
    # green for the wrong reason regardless of blank=True. test_user must
    # actually be allowed to change the row for the form to exercise anything.
    test_user.is_staff = True
    test_user.is_superuser = True
    test_user.save()

    model_admin = LadderCalibrationAdmin(LadderCalibration, admin.site)
    request = RequestFactory().get("/admin/gel_analyzer/laddercalibration/")
    request.user = test_user
    form_class = model_admin.get_form(request, obj=calib, change=True)

    data = {
        "analysis": str(calib.analysis_id),
        "ladder_lane": "",
        "template": "",
        "method": calib.method,
        "coefficients": json.dumps(calib.coefficients),
        "r_squared": str(calib.r_squared),
        "matched_band_count": str(calib.matched_band_count),
        "band_matches": json.dumps(calib.band_matches),
        "created_by": str(calib.created_by_id),
    }
    form = form_class(data=data, instance=calib)
    assert "template" in form.fields and "ladder_lane" in form.fields, (
        "form fields were stripped -- has_change_permission likely failed silently"
    )
    assert form.is_valid(), form.errors
    form.save()

    calib.refresh_from_db()
    assert calib.template_id is None
    assert calib.ladder_lane_id is None
