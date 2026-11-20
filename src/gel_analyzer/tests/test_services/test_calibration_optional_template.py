"""Verify calibration services accept template=None (PR #1 quantification port)."""

import dataclasses
import inspect

import pytest


@pytest.mark.unit
def test_calibrate_signature_accepts_optional_template():
    """CalibrationService.calibrate(template=None) is the new signature."""
    from gel_analyzer.services.calibration.service import CalibrationService

    sig = inspect.signature(CalibrationService.calibrate)
    template_param = sig.parameters.get("template")
    assert template_param is not None, "calibrate must take a 'template' parameter"
    # Default must be None OR the annotation must allow None
    assert template_param.default is None or "None" in str(template_param.annotation), (
        f"template must be optional. Annotation: {template_param.annotation}, default: {template_param.default}"
    )


@pytest.mark.unit
def test_calibrate_all_ladders_signature_accepts_optional_template():
    from gel_analyzer.services.calibration.multi_ladder_service import MultiLadderCalibrationService

    sig = inspect.signature(MultiLadderCalibrationService.calibrate_all_ladders)
    template_param = sig.parameters.get("template")
    assert template_param is not None
    assert template_param.default is None or "None" in str(template_param.annotation)


@pytest.mark.unit
def test_multi_ladder_result_template_name_nullable():
    """MultiLadderCalibrationResult.template_name allows None for manual-MW workflows."""
    from gel_analyzer.services.calibration.models import MultiLadderCalibrationResult

    field = next(
        (f for f in dataclasses.fields(MultiLadderCalibrationResult) if f.name == "template_name"),
        None,
    )
    assert field is not None
    # str | None type or default=None
    assert field.default is None or "None" in str(field.type)


@pytest.mark.django_db
def test_calibrate_works_without_template_when_lanes_have_assigned_mw(gel_analysis):
    """Behavioral test: CalibrationService.calibrate(lane, template=None) succeeds
    when the lane's bands have estimated_mw_kda assigned (manual MW workflow).

    This is the end-to-end guard for the code-review fix that made the
    template argument actually optional. Before the fix, the path was
    untested and a regression that re-required ``template`` would only be
    caught at the call site, not in the service layer.
    """
    from gel_analyzer.models import Band, Lane
    from gel_analyzer.services.calibration.service import CalibrationService

    # Ladder lane sized so Rf calculation is well-defined
    lane = Lane.objects.create(
        analysis=gel_analysis,
        lane_number=99,  # avoid clashing with other fixtures
        lane_type=Lane.LaneType.LADDER,
        detection_source=Lane.DetectionSource.MANUAL,
        x=10,
        y=10,
        width=20,
        height=200,
    )
    # 3 bands with manually-assigned MW (top → bottom = high MW → low MW)
    for y, mw in [(40, 50.0), (100, 25.0), (160, 10.0)]:
        Band.objects.create(
            lane=lane,
            detection_source=Band.DetectionSource.MANUAL,
            band_type=Band.BandType.MW_REFERENCE,
            position_y=y,
            estimated_mw_kda=mw,
            confidence=0.9,
        )

    # Call calibrate without a template — must not raise on template.bands /
    # template.name access and must produce a successful calibration.
    service = CalibrationService()
    result = service.calibrate(lane, template=None)

    assert result is not None
    assert result.success is True, (
        f"Expected calibration to succeed without template, got: success={result.success}, error={result.error_message}"
    )
    # Sanity-check the result actually used the assigned MW values
    assert result.r_squared > 0.0
    assert len(result.band_matches) == 3
