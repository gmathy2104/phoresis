"""Mecanisme B -- un limit_choices_to qui exclut la valeur COURANTE bloque le
re-enregistrement d'un ProteinQuantCalibrationPoint existant.

CE QUE CE FICHIER PROUVE
-------------------------
Audit d'acces du 2026-08-28 (docs/reviews/2026-08-28-audit-acces-volet-decisionnel.md
§4.3bis), mecanisme B : ProteinQuantCalibrationPoint.band restreint son choix aux
bandes band_type=CALIBRATION. Correct pour un NOUVEAU point -- mais si la bande est
reclassee APRES coup (band_type edite en dehors de ce point), la valeur courante
sort du filtre et tout ModelForm refuse le point tel quel avec "not a valid choice".

ProteinQuantCalibrationPoint n'a AUCUN ModelAdmin enregistre aujourd'hui (ni
MultiLadderCalibrationConfig, l'autre champ gel_analyzer sans admin) -- il n'y a
donc pas de "vrai formulaire admin" a instancier pour ce modele. Ce test utilise le
ModelForm generique que fields="__all__" produirait, qui est exactement ce que
l'audit lui-meme a mesure (§4.3bis precise que ces defauts se comptent en base
"sans instancier un seul formulaire", pas via l'admin reel). Le correctif au
niveau du champ protege donc n'importe quel formulaire futur, pas un ecran
existant.
"""

import pytest

from django import forms

from gel_analyzer.models import Band, ProteinQuantCalibrationPoint


@pytest.mark.django_db
def test_calibration_point_survives_resave_after_band_reclassified(calibration_band, test_user):
    """Un point de calibration cree sur une bande CALIBRATION, puis dont la bande
    est reclassee (band_type -> OTHER) apres coup, doit rester ré-enregistrable
    tel quel. Avant l'elargissement du limit_choices_to, ce geste repondait
    "Select a valid choice. That choice is not one of the available choices."
    sur band -- alors que c'est TOUJOURS le meme objet, jamais retouche par
    l'utilisateur.
    """
    point = ProteinQuantCalibrationPoint.objects.create(
        band=calibration_band,
        load_amount=10.0,
        load_unit=ProteinQuantCalibrationPoint.UNIT_UG,
        role=ProteinQuantCalibrationPoint.ROLE_CALIBRATION,
    )

    # La derive mesuree par l'audit : la bande est reclassee APRES la creation du
    # point, hors de tout controle de ce modele-ci.
    calibration_band.band_type = Band.BandType.OTHER
    calibration_band.save(update_fields=["band_type"])

    FormClass = forms.modelform_factory(ProteinQuantCalibrationPoint, fields="__all__")
    data = {
        "band": str(point.band_id),
        "load_amount": str(point.load_amount),
        "load_unit": point.load_unit,
        "is_excluded_from_fit": point.is_excluded_from_fit,
        "role": point.role,
    }
    form = FormClass(data=data, instance=point)
    assert form.is_valid(), form.errors
    form.save()

    point.refresh_from_db()
    assert point.band_id == calibration_band.id
