"""Back-fill DensitometryResult.estimated_amount_range on the estimates already stored (0010 adds the column).

Without it an estimate stored before 0010 stays unflagged until its calibration is saved again or its
densitometry re-run -- never, on an APPROVED analysis, which refuses both. The flag is derived from stored
values only (no amount moves), so approved analyses are back-filled too.

The rule is ``services/quantification/service.py::calibration_area_span`` + ``calibration_range_of``, COPIED
here because a migration never imports app code that may move: for each ACTIVE ProteinQuantCalibration, the
span is [min, max] corrected area of its standards -- CALIBRATION bands with a quantification point, in
CALIBRATION lanes -- minus its ``excluded_band_ids``; every stored estimate of a band of a SAMPLE/CONTROL lane
that is not an MW_REFERENCE (``apply_to_analysis``'s scope) becomes IN_RANGE / ABOVE_RANGE / BELOW_RANGE,
bounds inclusive; a NaN area or span stays null. An analysis without an active calibration, or whose standards
hold no area, stays null -- what ``apply_to_analysis`` writes there.

``bulk_update``: DensitometryResult has no history table. Reverse is a no-op: 0010's reverse drops the column.
"""

import math

from django.db import migrations


def backfill_estimated_amount_range(apps, schema_editor):
    Band = apps.get_model("gel_analyzer", "Band")
    DensitometryResult = apps.get_model("gel_analyzer", "DensitometryResult")
    ProteinQuantCalibration = apps.get_model("gel_analyzer", "ProteinQuantCalibration")

    for calibration in ProteinQuantCalibration.objects.filter(is_active=True).only("analysis_id", "excluded_band_ids"):
        excluded = {str(band_id) for band_id in calibration.excluded_band_ids or []}
        standards = Band.objects.filter(
            lane__analysis_id=calibration.analysis_id,
            lane__lane_type="CALIBRATION",
            band_type="CALIBRATION",
            quant_point__isnull=False,
        ).values_list("pk", "densitometry__corrected_area")
        areas = [area for band_id, area in standards if area is not None and str(band_id) not in excluded]
        if not areas:
            continue
        low, high = min(areas), max(areas)
        if math.isnan(low) or math.isnan(high):
            continue
        results = list(
            DensitometryResult.objects.filter(
                band__lane__analysis_id=calibration.analysis_id,
                band__lane__lane_type__in=("SAMPLE", "CONTROL"),
                estimated_amount__isnull=False,
            )
            .exclude(band__band_type="MW_REFERENCE")
            .only("pk", "corrected_area")
        )
        for result in results:
            area = result.corrected_area
            if math.isnan(area):
                result.estimated_amount_range = None
            elif area < low:
                result.estimated_amount_range = "BELOW_RANGE"
            elif area > high:
                result.estimated_amount_range = "ABOVE_RANGE"
            else:
                result.estimated_amount_range = "IN_RANGE"
        DensitometryResult.objects.bulk_update(results, ["estimated_amount_range"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("gel_analyzer", "0011_seed_gel_assays"),
    ]

    operations = [
        migrations.RunPython(backfill_estimated_amount_range, migrations.RunPython.noop),
    ]
