"""
Template Learning Service.

Learns expected Rf (relative migration) positions from annotated calibrations
and stores them in LadderBandDefinition for template-guided detection.
"""

from collections import defaultdict

import numpy as np

from django.db.models import QuerySet

from gel_analyzer.models import (
    LadderBandDefinition,
    LadderCalibration,
    LadderTemplate,
)
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


class TemplateLearningService:
    """
    Service for learning band Rf patterns from calibration data.

    This service analyzes existing LadderCalibration records to compute
    average Rf (relative migration) positions for each band in a template.
    These learned patterns enable template-guided band detection that
    filters ghost bands.
    """

    def learn_rf_patterns(
        self,
        template: LadderTemplate,
        calibration_ids: list[str] | None = None,
        min_samples: int = 1,
    ) -> dict:
        """
        Compute average Rf positions from calibrations and save to template.

        Args:
            template: The ladder template to update
            calibration_ids: Optional list of calibration IDs to use.
                           If None, uses all calibrations for this template.
            min_samples: Minimum number of samples required per band to save Rf

        Returns:
            Dict with statistics about the learning process:
            {
                'calibration_count': int,
                'updated_bands': int,
                'skipped_bands': int,
                'band_details': [{band_order, mw_kda, sample_count, rf, tolerance}, ...]
            }
        """
        # Get calibrations
        calibrations = LadderCalibration.objects.filter(template=template)
        if calibration_ids:
            calibrations = calibrations.filter(pk__in=calibration_ids)

        if not calibrations.exists():
            logger.warning(
                f"No calibrations found for template {template.code}",
                template_id=str(template.pk),
            )
            return {
                "calibration_count": 0,
                "updated_bands": 0,
                "skipped_bands": template.band_count,
                "band_details": [],
            }

        # Collect Rf values per band_order
        rf_by_band = defaultdict(list)
        intensity_by_band = defaultdict(list)

        for cal in calibrations:
            for match in cal.band_matches:
                band_order = match.get("template_band_order")
                rf = match.get("rf")

                if band_order is not None and rf is not None:
                    rf_by_band[band_order].append(rf)

                    # Collect intensity if available for ranking
                    intensity = match.get("peak_intensity")
                    if intensity is not None:
                        intensity_by_band[band_order].append(intensity)

        # Compute averages and update template bands
        updated_bands = 0
        skipped_bands = 0
        band_details = []

        for band in template.bands.order_by("band_order"):
            rf_values = rf_by_band.get(band.band_order, [])
            sample_count = len(rf_values)

            detail = {
                "band_order": band.band_order,
                "mw_kda": band.mw_kda,
                "sample_count": sample_count,
                "rf": None,
                "tolerance": None,
                "intensity_rank": None,
            }

            if sample_count >= min_samples:
                # Compute mean Rf
                mean_rf = float(np.mean(rf_values))
                # Compute tolerance as 2 standard deviations (or minimum 0.02)
                if sample_count > 1:
                    std_rf = float(np.std(rf_values))
                    tolerance = max(0.02, std_rf * 2)
                else:
                    tolerance = 0.05  # Default tolerance for single sample

                # Update band
                band.expected_rf = mean_rf
                band.expected_rf_tolerance = min(tolerance, 0.15)  # Cap at 0.15
                band.save(update_fields=["expected_rf", "expected_rf_tolerance"])

                detail["rf"] = mean_rf
                detail["tolerance"] = band.expected_rf_tolerance
                updated_bands += 1
            else:
                skipped_bands += 1

            band_details.append(detail)

        # Compute intensity ranks (brightest = 1)
        self._update_intensity_ranks(template, intensity_by_band)

        logger.info(
            f"Learned Rf patterns for template {template.code}: "
            f"{updated_bands}/{template.band_count} bands updated from "
            f"{calibrations.count()} calibrations",
            template_id=str(template.pk),
        )

        return {
            "calibration_count": calibrations.count(),
            "updated_bands": updated_bands,
            "skipped_bands": skipped_bands,
            "band_details": band_details,
        }

    def _update_intensity_ranks(
        self,
        template: LadderTemplate,
        intensity_by_band: dict[int, list[float]],
    ) -> None:
        """
        Compute and update intensity ranks for template bands.

        Args:
            template: The ladder template
            intensity_by_band: Dict of band_order -> list of intensities
        """
        if not intensity_by_band:
            return

        # Compute average intensity per band
        avg_intensities = {}
        for band_order, intensities in intensity_by_band.items():
            avg_intensities[band_order] = np.mean(intensities)

        # Sort by intensity (descending) and assign ranks
        sorted_orders = sorted(
            avg_intensities.keys(),
            key=lambda bo: avg_intensities[bo],
            reverse=True,
        )

        rank = 1
        for band_order in sorted_orders:
            try:
                band = template.bands.get(band_order=band_order)
                band.intensity_rank = rank
                band.save(update_fields=["intensity_rank"])
                rank += 1
            except LadderBandDefinition.DoesNotExist:
                continue

    def compute_rf_statistics(
        self,
        template: LadderTemplate,
        calibrations: QuerySet | None = None,
    ) -> list[dict]:
        """
        Compute Rf statistics for display without saving.

        Used by training view to preview computed values before saving.

        Args:
            template: The ladder template
            calibrations: Optional queryset of calibrations to use

        Returns:
            List of dicts with band statistics:
            [{
                'band_order': int,
                'mw_kda': float,
                'current_expected_rf': float|None,
                'current_tolerance': float|None,
                'sample_count': int,
                'computed_rf': float|None,
                'computed_std': float|None,
                'computed_tolerance': float|None,
            }, ...]
        """
        if calibrations is None:
            calibrations = LadderCalibration.objects.filter(template=template)

        # Collect Rf values
        rf_by_band = defaultdict(list)
        for cal in calibrations:
            for match in cal.band_matches:
                band_order = match.get("template_band_order")
                rf = match.get("rf")
                if band_order is not None and rf is not None:
                    rf_by_band[band_order].append(rf)

        # Build statistics
        results = []
        for band in template.bands.order_by("band_order"):
            rf_values = rf_by_band.get(band.band_order, [])
            sample_count = len(rf_values)

            result = {
                "band_order": band.band_order,
                "mw_kda": band.mw_kda,
                "current_expected_rf": band.expected_rf,
                "current_tolerance": band.expected_rf_tolerance,
                "current_intensity_rank": band.intensity_rank,
                "sample_count": sample_count,
                "computed_rf": None,
                "computed_std": None,
                "computed_tolerance": None,
            }

            if sample_count > 0:
                result["computed_rf"] = float(np.mean(rf_values))
                if sample_count > 1:
                    std = float(np.std(rf_values))
                    result["computed_std"] = std
                    result["computed_tolerance"] = max(0.02, std * 2)

            results.append(result)

        return results

    def clear_rf_patterns(self, template: LadderTemplate) -> int:
        """
        Clear all learned Rf patterns from a template.

        Args:
            template: The ladder template

        Returns:
            Number of bands cleared
        """
        updated = template.bands.update(
            expected_rf=None,
            expected_rf_tolerance=0.05,  # Reset to default
            intensity_rank=None,
        )

        logger.info(
            f"Cleared Rf patterns for template {template.code}: {updated} bands",
            template_id=str(template.pk),
        )

        return updated

    def get_training_summary(self, template: LadderTemplate) -> dict:
        """
        Get summary of training data for a template.

        Args:
            template: The ladder template

        Returns:
            Dict with training summary:
            {
                'template_id': str,
                'template_name': str,
                'total_calibrations': int,
                'bands_with_rf': int,
                'bands_without_rf': int,
                'is_trained': bool,
                'training_quality': 'excellent'|'good'|'needs_more_data'|'untrained'
            }
        """
        calibrations = LadderCalibration.objects.filter(template=template)
        bands_with_rf = template.bands.filter(expected_rf__isnull=False).count()
        total_bands = template.band_count

        # Determine training quality
        if bands_with_rf == 0:
            quality = "untrained"
        elif bands_with_rf < total_bands:
            quality = "needs_more_data"
        elif calibrations.count() >= 3:
            quality = "excellent"
        else:
            quality = "good"

        return {
            "template_id": str(template.pk),
            "template_name": template.name,
            "total_calibrations": calibrations.count(),
            "bands_with_rf": bands_with_rf,
            "bands_without_rf": total_bands - bands_with_rf,
            "is_trained": bands_with_rf > 0,
            "training_quality": quality,
        }
