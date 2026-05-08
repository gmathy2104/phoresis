"""Recompute the active protein quantification calibration after densitometry changes.

Called at the end of `run_densitometry_task` (after the bulk write-back), NOT from
the densito invalidation signal — at signal-fire time the DensitometryResult rows
have just been deleted, so corrected_area is unavailable. The recompute window is
post-densitometry-write."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import GelAnalysis

logger = get_logger(__name__)


def recompute_if_active(analysis: GelAnalysis) -> int:
    """If the analysis has an active ProteinQuantCalibration, refit it from the
    current densitometry and reapply (writes DensitometryResult.estimated_amount
    on every SAMPLE/CONTROL band). Returns count of rows updated; 0 if no active
    calibration exists or if refit failed."""
    from gel_analyzer.models import ProteinQuantCalibration

    from .models import QuantParams
    from .service import ProteinQuantCalibrationService

    active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
    if active is None:
        return 0

    svc = ProteinQuantCalibrationService(QuantParams(method=active.method, unit=active.unit))
    points = svc.collect_calibration_points(analysis)
    result = svc.fit(points, excluded_band_ids=active.excluded_band_ids)
    if not result.success:
        logger.warning(
            f"recompute_if_active({analysis.pk}): refit failed: {result.error_message}"
        )
        return 0

    # Update the active row's coefficients in place (no new active record — we are
    # responding to upstream densito changes, not to a user-initiated recalibration).
    # last_recomputed_at lets the audit history distinguish a user save from a
    # background drift caused by band edits, splits, or re-running densitometry.
    from django.utils import timezone

    active.coefficients = result.coefficients
    active.r_squared = result.r_squared
    active.equation = result.equation
    active.last_recomputed_at = timezone.now()
    active.save(update_fields=["coefficients", "r_squared", "equation", "last_recomputed_at"])

    return svc.apply_to_analysis(active)
