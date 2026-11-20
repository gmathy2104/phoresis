"""Verify ProteinQuantCalibrationPoint + ProteinQuantCalibration models."""

import uuid

import pytest

from django.db.models import Q

from gel_analyzer.models import ProteinQuantCalibration, ProteinQuantCalibrationPoint


@pytest.mark.unit
def test_calibration_point_has_band_one_to_one():
    field = ProteinQuantCalibrationPoint._meta.get_field("band")
    assert field.one_to_one
    # limit_choices_to is a callable (not a bare dict) since the ré-enregistrement
    # fix -- see gel_analyzer/models/quantification.py::calibration_point_band_choices.
    # Widened by OR so a band already carrying ITS OWN quant_point stays a legal
    # choice on re-save even if band_type drifted away from CALIBRATION afterwards.
    limit_choices_to = field.remote_field.limit_choices_to
    assert callable(limit_choices_to)
    assert limit_choices_to() == (Q(band_type="CALIBRATION") | Q(quant_point__isnull=False))


@pytest.mark.unit
def test_calibration_point_role_choices():
    field = ProteinQuantCalibrationPoint._meta.get_field("role")
    role_keys = {key for key, _ in field.choices}
    assert role_keys == {"CALIBRATION", "CONTROL"}


@pytest.mark.unit
def test_calibration_point_unit_choices():
    field = ProteinQuantCalibrationPoint._meta.get_field("load_unit")
    unit_keys = {key for key, _ in field.choices}
    assert unit_keys == {"UG", "UG_ML"}


@pytest.mark.unit
def test_protein_quant_calibration_uses_uuid_pk():
    field = ProteinQuantCalibration._meta.get_field("id")
    assert isinstance(field, type(ProteinQuantCalibration._meta.get_field("id")))  # field type
    # Confirm primary key + uuid default
    assert field.primary_key
    # Test the default returns a uuid
    val = field.default()
    assert isinstance(val, uuid.UUID)


@pytest.mark.unit
def test_protein_quant_calibration_method_choices():
    field = ProteinQuantCalibration._meta.get_field("method")
    method_keys = {key for key, _ in field.choices}
    assert method_keys == {"LINEAR", "POLYNOMIAL_2", "FOUR_PL"}


@pytest.mark.unit
def test_protein_quant_calibration_unique_active_per_analysis():
    """Only one is_active=True per analysis."""
    constraints = ProteinQuantCalibration._meta.constraints
    names = [c.name for c in constraints]
    assert "uniq_active_quant_calibration_per_analysis" in names


@pytest.mark.unit
def test_protein_quant_calibration_analysis_related_name_plural():
    field = ProteinQuantCalibration._meta.get_field("analysis")
    # GelAnalysis.quant_calibrations (plural) — supports older fits with
    # is_active=False for audit.
    assert field.remote_field.related_name == "quant_calibrations"


@pytest.mark.unit
def test_protein_quant_calibration_has_last_recomputed_at():
    field = ProteinQuantCalibration._meta.get_field("last_recomputed_at")
    assert field.null is True
    assert field.blank is True
