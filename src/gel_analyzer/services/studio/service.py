"""Ladder Template Studio — orchestrates cross-gel training.

The Studio lets a user pick 3-10 LADDER lanes across existing gels,
run a top-N-by-intensity auto-assignment, and commit all calibrations
+ template Rf learning atomically.

Reuses `CalibrationService` for single-lane match_bands_to_template +
calibrate, and `TemplateLearningService.learn_rf_patterns` for the
final template update.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from gel_analyzer.models import Band, LadderCalibration, LadderTemplate, Lane
from gel_analyzer.services.calibration.models import BandMatch
from gel_analyzer.services.calibration.service import CalibrationService
from gel_analyzer.services.template_learning import TemplateLearningService
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


class StudioService:
    """Cross-gel ladder template training orchestration."""

    def __init__(self) -> None:
        self.calibration_service = CalibrationService()
        self.learning_service = TemplateLearningService()

    # ------------------------------------------------------------------
    # Lane discovery
    # ------------------------------------------------------------------

    def list_available_lanes(
        self,
        template: LadderTemplate,
        *,
        analysis_id: str | None = None,
        only_with_bands: bool = True,
        exclude_already_calibrated_for_this_template: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Return LADDER lanes across analyses with summary metadata.

        Filters are additive. Ordering: most recent analysis first.
        """
        qs = (
            Lane.objects.filter(lane_type="LADDER")
            .select_related("analysis", "analysis__gel_image")
            .order_by("-analysis__created_at", "lane_number")
        )
        if analysis_id:
            qs = qs.filter(analysis_id=analysis_id)
        if only_with_bands:
            qs = qs.filter(bands__isnull=False).distinct()
        if exclude_already_calibrated_for_this_template:
            existing = LadderCalibration.objects.filter(template=template, ladder_lane__in=qs).values_list(
                "ladder_lane_id", flat=True
            )
            qs = qs.exclude(id__in=list(existing))

        total = qs.count()
        rows = []
        for lane in qs[offset : offset + limit]:
            analysis = lane.analysis
            gel_image = analysis.gel_image if analysis else None
            band_count = lane.bands.count()
            has_calibration = LadderCalibration.objects.filter(template=template, ladder_lane=lane).exists()
            rows.append(
                {
                    "lane_id": str(lane.id),
                    "lane_number": lane.lane_number,
                    "analysis_id": str(analysis.id) if analysis else None,
                    "analysis_name": analysis.name if analysis else "",
                    "gel_image_id": str(gel_image.id) if gel_image else None,
                    "gel_image_filename": (gel_image.original_filename if gel_image else ""),
                    "gel_image_width": gel_image.width if gel_image else None,
                    "gel_image_height": gel_image.height if gel_image else None,
                    "created_at": analysis.created_at.isoformat() if analysis else None,
                    "band_count": band_count,
                    "already_calibrated_for_this_template": has_calibration,
                    "lane_bbox": {
                        "x": lane.x,
                        "y": lane.y,
                        "width": lane.width,
                        "height": lane.height,
                    },
                }
            )
        return {"total": total, "rows": rows, "limit": limit, "offset": offset}

    # ------------------------------------------------------------------
    # Auto-assignment (top-N by intensity + Hungarian/RANSAC matching)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Profile-based re-detection (rolling-ball + d1/d2, for faint bands)
    # ------------------------------------------------------------------

    def redetect_with_profile(self, lane_ids: list[str]) -> dict:
        """Run profile-based detection on a set of lanes.

        Pipeline: ``IntensityProfileExtractor`` → ``ProfileProcessor``
        (rolling-ball noise subtraction + baseline correction) → d1/d2
        derivative detection with aggressive settings (low SNR, short
        band width) to surface faint bands that CV2 missed.

        Returns ``{"lanes": {lane_id: {"candidates": [...], "profile_summary": {...}}}}``.
        Candidates are in-memory only — not persisted. They override the
        DB bands for a subsequent ``auto_assign`` call.
        """
        if not lane_ids:
            return {"lanes": {}}

        from gel_analyzer.services.band_detection import BandDetectionParams
        from gel_analyzer.services.band_detection.derivative_detector import DerivativeDetector
        from gel_analyzer.services.band_detection.profile_extractor import IntensityProfileExtractor
        from gel_analyzer.services.band_detection.profile_processor import ProfileProcessor
        from gel_analyzer.services.file_handler import GelFileHandler

        lanes = list(Lane.objects.filter(id__in=lane_ids, lane_type="LADDER").select_related("analysis__gel_image"))
        results: dict[str, dict] = {}
        for lane in lanes:
            try:
                image = GelFileHandler.load_image_as_array(lane.analysis.gel_image)
            except Exception as exc:  # pragma: no cover — defensive
                results[str(lane.id)] = {"candidates": [], "error": f"load_image_failed: {exc}"}
                continue

            # Aggressive params for faint-band recovery: lower SNR floor,
            # smaller min band width. Rolling-ball stays at defaults (
            # large enough to subtract long-wavelength background while
            # preserving peak shape).
            params = BandDetectionParams(
                min_snr=1.0,
                min_band_width_px=3,
                threshold_factor=0.3,
            )

            extractor = IntensityProfileExtractor(params)
            processor = ProfileProcessor(params)
            detector = DerivativeDetector(params)

            try:
                profile = extractor.extract_profile(image, lane)
                profile = processor.process(profile)
                peaks, threshold = detector.detect(profile)
            except Exception as exc:
                logger.warning(f"Profile redetect failed on lane {lane.id}: {exc}")
                results[str(lane.id)] = {"candidates": [], "error": str(exc)}
                continue

            candidates = [
                {
                    "position_y": int(p.y_position),
                    "intensity_peak": float(p.height),
                    "peak_prominence": float(p.prominence),
                    "snr": float(p.snr),
                    "width_px": float(p.width_px),
                    # Minimal bbox — lane width, small vertical padding; kept
                    # so the strip view has something to draw. Overridden by
                    # the front-end with the lane crop scale anyway.
                    "bbox_x": lane.x,
                    "bbox_y": max(lane.y, int(p.y_position) - 4),
                    "bbox_width": lane.width,
                    "bbox_height": 8,
                }
                for p in peaks
            ]
            results[str(lane.id)] = {
                "candidates": candidates,
                "profile_summary": {
                    "lane_id": str(lane.id),
                    "lane_number": lane.lane_number,
                    "peak_count": len(candidates),
                    "threshold": float(threshold),
                    "existing_band_count": lane.bands.count(),
                },
            }
        return {"lanes": results}

    def auto_assign(
        self,
        template: LadderTemplate,
        lane_ids: list[str],
        override_bands: dict[str, list[dict]] | None = None,
    ) -> dict:
        """For each lane, take the top-N brightest bands (N = template.band_count),
        delegate to CalibrationService for matching + R² + residuals.

        Returns:
            {
                "template_id": str,
                "band_count_expected": int,
                "lanes": [
                    {
                        "lane_id": str,
                        "lane_number": int,
                        "analysis_id": str,
                        "analysis_name": str,
                        "total_bands_detected": int,
                        "kept_bands": int,   # = min(detected, band_count)
                        "matches": [BandMatch dict, ...],
                        "r_squared": float | None,
                        "equation": str | None,
                        "flagged_count": int,
                        "warnings": [str, ...],
                    },
                    ...
                ],
            }
        """
        if not lane_ids:
            return {
                "template_id": str(template.pk),
                "band_count_expected": template.band_count,
                "lanes": [],
            }

        lanes = list(Lane.objects.filter(id__in=lane_ids, lane_type="LADDER").select_related("analysis"))
        # Preserve caller-provided ordering.
        lanes_by_id = {str(lane.id): lane for lane in lanes}
        ordered = [lanes_by_id[str(lid)] for lid in lane_ids if str(lid) in lanes_by_id]

        override_bands = override_bands or {}
        lane_results: list[dict] = []
        for lane in ordered:
            lane_override = override_bands.get(str(lane.id))
            lane_results.append(self._auto_assign_one(lane, template, lane_override))

        return {
            "template_id": str(template.pk),
            "band_count_expected": template.band_count,
            "lanes": lane_results,
        }

    def _auto_assign_one(
        self,
        lane: Lane,
        template: LadderTemplate,
        override_bands: list[dict] | None = None,
    ) -> dict:
        """Resolve per-lane matches. Prefers already-existing human calibration.

        Strategy (in priority order):
        1. **Existing calibration** — if this lane already has a
           ``LadderCalibration`` for this template, return its saved
           ``band_matches`` directly. These are ground truth (human-reviewed
           or previously-validated). Matching them again would just introduce
           algorithm noise on data that's already correct.
        2. **Rf-prior matching** — new/uncalibrated lanes with a trained
           template: pick the most intense band within ±expected_rf_tolerance
           for each expected MW (polarity-agnostic, position-based). Falls
           back to a Hungarian re-match if R² is poor.
        3. **Top-N by intensity** — untrained template: legacy greedy picker.
        """
        n_expected = template.band_count
        if override_bands is not None:
            # Re-detected candidates supplied from the Studio — ephemeral
            # stand-in for lane.bands; carries the same attribute surface
            # (.id, .position_y, .intensity_peak, .peak_prominence,
            # .bbox_*) that CalibrationService + serialisers expect.
            all_bands = [self._candidate_to_ephemeral_band(c, lane) for c in override_bands]
        else:
            all_bands = list(lane.bands.all())
        total = len(all_bands)

        warnings: list[str] = []
        if override_bands is not None:
            warnings.append(f"Using {total} re-detected candidate(s) from profile + noise-subtraction (ephemeral).")
        if total == 0:
            warnings.append("No bands detected in this lane.")

        lane_top = lane.y
        lane_bottom = lane.y + lane.height

        def rf_for(b: Band) -> float:
            return self.calibration_service._calculate_rf(b.position_y, lane_top, lane_bottom)

        # Pre-compute the Rf of every detected band (used by all_bands serialization).
        bands_with_rf = [(b, rf_for(b)) for b in all_bands]
        band_by_id = {str(b.id): b for b in all_bands}

        base_result: dict[str, Any] = {
            "lane_id": str(lane.id),
            "lane_number": lane.lane_number,
            "analysis_id": str(lane.analysis_id) if lane.analysis_id else None,
            "analysis_name": lane.analysis.name if lane.analysis else "",
            "total_bands_detected": total,
            "kept_bands": 0,
            "matches": [],
            "all_bands": [
                {
                    "band_id": str(b.id),
                    "position_y": b.position_y,
                    "bbox_y": b.bbox_y,
                    "bbox_height": b.bbox_height,
                    "rf": round(rf, 4),
                    "intensity_peak": float(b.intensity_peak) if b.intensity_peak is not None else None,
                    "peak_prominence": (
                        float(b.peak_prominence) if getattr(b, "peak_prominence", None) is not None else None
                    ),
                }
                for b, rf in bands_with_rf
            ],
            "r_squared": None,
            "equation": None,
            "flagged_count": 0,
            "matching_strategy": None,
            "warnings": warnings,
        }
        if not all_bands:
            return base_result

        template_bands = list(template.bands.order_by("band_order"))

        # 1 — Existing calibration takes precedence. Don't re-match data that's
        # already been curated. Skipped when re-detection candidates are
        # supplied — the whole point of a redetect is to replace the bands.
        existing_cal = (
            None
            if override_bands is not None
            else LadderCalibration.objects.filter(template=template, ladder_lane=lane).first()
        )
        if existing_cal and existing_cal.band_matches:
            matches, cal_notes = self._matches_from_calibration(existing_cal, band_by_id, template_bands, rf_for)
            if matches:
                strategy_notes = cal_notes
                base_result["matching_strategy"] = "existing_calibration"
                # Skip the algorithmic paths; jump to post-processing.
                return self._finalize_result(
                    base_result,
                    matches,
                    strategy_notes,
                    warnings,
                    all_bands,
                    lane,
                    template,
                    existing_cal,
                )

        has_priors = all(tb.expected_rf is not None for tb in template_bands)

        if has_priors:
            matches, strategy_notes = self._match_with_rf_priors(bands_with_rf, template_bands)
            base_result["matching_strategy"] = "rf_priors"
        else:
            # Legacy: top-N by intensity, then CalibrationService matching.
            bands_sorted_by_intensity = sorted(
                all_bands,
                key=lambda b: b.intensity_peak or 0.0,
                reverse=True,
            )
            kept = bands_sorted_by_intensity[:n_expected]
            if total > n_expected:
                warnings.append(f"{total - n_expected} extra band(s) dropped (kept top {n_expected} by intensity).")
            elif total < n_expected:
                warnings.append(f"Only {total} bands detected; template expects {n_expected}.")
            kept_sorted = sorted(kept, key=lambda b: b.position_y)
            detected_with_rf = [(b, rf_for(b)) for b in kept_sorted]
            n_detected = len(detected_with_rf)
            n_template = len(template_bands)
            if n_detected == n_template:
                matches = [
                    BandMatch(
                        band_id=str(band.id),
                        template_band_order=tb.band_order,
                        mw_kda=tb.mw_kda,
                        position_y=band.position_y,
                        rf=rf,
                    )
                    for (band, rf), tb in zip(detected_with_rf, template_bands, strict=False)
                ]
            elif n_detected > n_template:
                matches = self.calibration_service._match_with_outlier_detection(
                    detected_with_rf, template_bands, lane_top, lane_bottom
                )
            else:
                matches = self.calibration_service._match_with_missing_bands(
                    detected_with_rf, template_bands, lane_top, lane_bottom
                )
            strategy_notes: list[str] = []
            base_result["matching_strategy"] = "top_n_intensity"

        return self._finalize_result(
            base_result,
            matches,
            strategy_notes,
            warnings,
            all_bands,
            lane,
            template,
            None,
        )

    def _finalize_result(
        self,
        base_result: dict,
        matches: list[BandMatch],
        strategy_notes: list[str],
        warnings: list[str],
        all_bands: list,
        lane: Lane,
        template: LadderTemplate,
        existing_cal: LadderCalibration | None,
    ) -> dict:
        """Compute R² / flags / all_bands annotations for any matching strategy."""
        warnings.extend(strategy_notes)
        base_result["kept_bands"] = len(matches)

        # When we trust an existing calibration, reuse its persisted R² and
        # coefficients rather than re-fitting. Otherwise re-calibrate from the
        # fresh matches.
        if existing_cal is not None:
            for m in matches:
                m.peak_intensity = self._peak_intensity_for_band_id(all_bands, m.band_id)
            self._flag_matches(template, matches, existing_cal.r_squared)
            r_squared = existing_cal.r_squared
            equation = existing_cal.equation_display
            calib_warnings: list[str] = []
            finalized_matches = matches
        else:
            calib_result = self._auto_select_calibration(lane, template, matches)
            for m in calib_result.band_matches or []:
                m.peak_intensity = self._peak_intensity_for_band_id(all_bands, m.band_id)
            self._flag_matches(template, calib_result.band_matches or [], calib_result.r_squared)
            r_squared = calib_result.r_squared
            equation = calib_result.equation
            calib_warnings = list(calib_result.warnings or [])
            if not calib_result.success and calib_result.error_message:
                calib_warnings.append(calib_result.error_message)
            finalized_matches = calib_result.band_matches or []

        # Drop matches whose residual / aligned-expected_rf distance is too
        # large — better UX to show a slot as "missing" (red ‒) than as a
        # forced wrong label wearing a flag badge.
        template_bands_all = list(template.bands.order_by("band_order"))
        finalized_matches, drop_warnings = self._drop_bad_matches(finalized_matches, template_bands_all, r_squared)
        calib_warnings.extend(drop_warnings)

        # Pairwise consistency checks — supplement R² with independent
        # cross-band checks so single mis-assignments can't hide in the fit.
        suspect_indices, consistency_warnings = self._pairwise_consistency_check(finalized_matches, template_bands_all)
        for i, m in enumerate(finalized_matches):
            if i in suspect_indices:
                m.flagged = True
        flagged = sum(1 for m in finalized_matches if getattr(m, "flagged", False))
        calib_warnings.extend(consistency_warnings)

        # Annotate all_bands with matched/flagged flags for strip rendering.
        matched_by_id: dict[str, dict] = {}
        for m in finalized_matches:
            matched_by_id[str(m.band_id)] = {
                "mw_kda": m.mw_kda,
                "template_band_order": m.template_band_order,
                "flagged": bool(getattr(m, "flagged", False)),
            }
        for entry in base_result["all_bands"]:
            info = matched_by_id.get(entry["band_id"])
            entry["matched"] = info is not None
            entry["matched_mw_kda"] = info["mw_kda"] if info else None
            entry["matched_flagged"] = info["flagged"] if info else False

        base_result.update(
            {
                "matches": [self._serialize_match(m) for m in finalized_matches],
                "r_squared": float(r_squared) if r_squared is not None else None,
                "equation": equation,
                "flagged_count": flagged,
            }
        )
        warnings.extend(calib_warnings)
        return base_result

    def _matches_from_calibration(
        self,
        calibration: LadderCalibration,
        band_by_id: dict,
        template_bands: list,
        rf_for,
    ) -> tuple[list[BandMatch], list[str]]:
        """Rebuild BandMatch objects from the stored band_matches JSON.

        The saved JSON may reference band ids that have since been deleted; we
        skip those with a note rather than failing the whole lane.
        """
        template_band_by_order = {tb.band_order: tb for tb in template_bands}
        matches: list[BandMatch] = []
        notes: list[str] = []
        missing = 0
        for raw in calibration.band_matches or []:
            band_id = str(raw.get("band_id"))
            band = band_by_id.get(band_id)
            if band is None:
                missing += 1
                continue
            order = raw.get("template_band_order")
            tb = template_band_by_order.get(order)
            mw = raw.get("mw_kda") if tb is None else tb.mw_kda
            # Recompute Rf from the current band position (lane bounds may have
            # shifted since the calibration was saved); fall back to the saved
            # value if the band is position-less.
            rf_value = rf_for(band) if band.position_y is not None else raw.get("rf", 0.0)
            matches.append(
                BandMatch(
                    band_id=band_id,
                    template_band_order=order,
                    mw_kda=float(mw) if mw is not None else 0.0,
                    position_y=band.position_y,
                    rf=float(rf_value),
                )
            )
        if missing:
            notes.append(
                f"Used existing calibration — {missing} stored match(es) referenced deleted bands and were skipped."
            )
        else:
            notes.append("Used existing calibration (saved band↔MW matches, no re-matching).")
        return matches, notes

    def _auto_select_calibration(
        self,
        lane: Lane,
        template: LadderTemplate,
        matches: list[BandMatch],
    ):
        """Pick the best fit method between LOG_LINEAR / POLYNOMIAL_2 / POLYNOMIAL_3.

        Linear gels give a clean log-linear Rf vs log10(MW) relationship —
        LOG_LINEAR wins. Gradient gels (variable acrylamide %) curve that
        relationship, so a polynomial fit with 2-3 degrees captures the
        extremes better. We try all three methods and pick the one with the
        lowest AIC (which naturally penalises extra parameters so a
        polynomial only wins when its lower residuals justify its cost).

        Falls back to LOG_LINEAR when bands are too few to fit polynomials.
        """
        import math

        import numpy as np

        from gel_analyzer.services.calibration.models import CalibrationParams

        n = len(matches)
        if n < 3:
            # Delegate to default behaviour for tiny inputs.
            return self.calibration_service.calibrate(lane=lane, template=template, matches=matches)

        candidate_methods = [("LOG_LINEAR", 2)]
        if n >= 4:
            candidate_methods.append(("POLYNOMIAL_2", 3))
        if n >= 5:
            candidate_methods.append(("POLYNOMIAL_3", 4))

        best = None
        best_aic = math.inf
        for method, k in candidate_methods:
            service = CalibrationService(CalibrationParams(method=method, min_bands=3))
            result = service.calibrate(lane=lane, template=template, matches=[self._clone_match(m) for m in matches])
            if not result.success or result.r_squared is None:
                continue
            # Reconstruct SSR from residuals stored on match objects.
            residuals = np.array(
                [float(getattr(mm, "residual", 0.0) or 0.0) for mm in result.band_matches or []],
                dtype=float,
            )
            ssr = float(np.sum(residuals**2))
            if ssr <= 0 or n - k <= 0:
                continue
            # AIC for Gaussian residuals: n·ln(SSR/n) + 2k.
            aic = n * math.log(ssr / n) + 2 * k
            if aic < best_aic:
                best_aic = aic
                best = result
                best._studio_method = method

        if best is None:
            return self.calibration_service.calibrate(lane=lane, template=template, matches=matches)

        if getattr(best, "_studio_method", None) and best._studio_method != "LOG_LINEAR":
            msg = f"Fit auto-selected: {best._studio_method} (better AIC than LOG_LINEAR — possible gradient gel)."
            best.warnings = list(best.warnings or [])
            if msg not in best.warnings:
                best.warnings.append(msg)
        return best

    @staticmethod
    def _clone_match(m: BandMatch) -> BandMatch:
        """Shallow clone so CalibrationService's per-fit mutation of
        ``residual`` doesn't bleed across candidate methods."""
        return BandMatch(
            band_id=m.band_id,
            template_band_order=m.template_band_order,
            mw_kda=m.mw_kda,
            position_y=m.position_y,
            rf=m.rf,
        )

    def _match_with_rf_priors(
        self,
        bands_with_rf: list[tuple],
        template_bands: list,
    ) -> tuple[list[BandMatch], list[str]]:
        """Two-pass Hungarian + RANSAC with run-time auto-alignment.

        Gels run for different durations (or with different well/dye-front
        positions) produce the same ladder at different absolute Rf values —
        the relationship is ``observed_rf ≈ α · template_rf + β``. Matching
        against trained expected_rf directly fails in that case, because the
        tight tolerance windows don't overlap the actual bands.

        Tour 1 (wide window, tolerance_scale=3) gets a rough assignment.
        If enough matches land, we fit ``α, β`` from them and RESCALE the
        template's expected_rf into the lane's frame. Tour 2 (tight
        window on the aligned priors) produces the final matches. RANSAC
        refines by swapping outliers with better in-window candidates.
        """
        notes: list[str] = []
        if not bands_with_rf:
            return [], notes
        if len(bands_with_rf) < 3 or len(template_bands) < 3:
            # Fall through directly to the single-pass matcher for tiny inputs.
            return self._hungarian_ransac_core(
                bands_with_rf,
                [(tb, float(tb.expected_rf), float(tb.expected_rf_tolerance or 0.05)) for tb in template_bands],
                notes=notes,
                tol_mul=3.0,
            )

        # Tour 1 — wide window, use raw expected_rf.
        tour1_targets = [(tb, float(tb.expected_rf), float(tb.expected_rf_tolerance or 0.05)) for tb in template_bands]
        tour1, tour1_notes = self._hungarian_ransac_core(
            bands_with_rf, tour1_targets, notes=[], tol_mul=3.0, ransac=False
        )

        alpha, beta, alignment_note = self._fit_lane_alignment(tour1, template_bands)
        if alignment_note is not None:
            notes.append(alignment_note)

        # Tour 2 — tight window on aligned priors. If alignment is trivial
        # (α≈1, β≈0), the aligned targets equal the trained ones and we just
        # refine the tour 1 assignments.
        tour2_targets = [
            (
                tb,
                alpha * float(tb.expected_rf) + beta,
                float(tb.expected_rf_tolerance or 0.05) * max(1.0, alpha),
            )
            for tb in template_bands
        ]
        matches, tour2_notes = self._hungarian_ransac_core(
            bands_with_rf, tour2_targets, notes=[], tol_mul=2.0, ransac=True
        )
        notes.extend(tour2_notes)
        return matches, notes

    def _fit_lane_alignment(
        self,
        tour1_matches: list[BandMatch],
        template_bands: list,
    ) -> tuple[float, float, str | None]:
        """Fit α, β s.t. observed_rf ≈ α · expected_rf + β.

        Returns ``(alpha, beta, note_or_None)``. When too few matches land
        or the fit is degenerate, returns ``(1.0, 0.0, None)`` so tour 2
        behaves like a single-pass matcher.
        """
        import numpy as np

        if len(tour1_matches) < 4:
            return 1.0, 0.0, None

        tb_by_order = {tb.band_order: tb for tb in template_bands}
        xs, ys = [], []
        for m in tour1_matches:
            tb = tb_by_order.get(m.template_band_order)
            if tb is None or tb.expected_rf is None:
                continue
            xs.append(float(tb.expected_rf))
            ys.append(float(m.rf))
        if len(xs) < 4:
            return 1.0, 0.0, None

        xs_arr = np.array(xs, dtype=float)
        ys_arr = np.array(ys, dtype=float)
        if float(np.std(xs_arr)) < 1e-4:
            return 1.0, 0.0, None
        alpha, beta = np.polyfit(xs_arr, ys_arr, 1)

        if not (0.3 <= alpha <= 3.0):
            # Degenerate alignment (fit likely driven by mis-matches).
            return 1.0, 0.0, (f"Alignment rejected (α={alpha:.3f} outside sane range) — using raw trained priors.")
        # Only flag a note if the alignment moves things meaningfully.
        if abs(alpha - 1.0) > 0.1 or abs(beta) > 0.03:
            return (
                float(alpha),
                float(beta),
                f"Lane auto-aligned to trained template: Rf_obs ≈ {alpha:.3f}·Rf_tmpl + {beta:+.3f} (likely different run time / gel height).",
            )
        return float(alpha), float(beta), None

    def _hungarian_ransac_core(
        self,
        bands_with_rf: list[tuple],
        targets: list[tuple],  # [(tb, target_rf, tolerance), ...]
        *,
        notes: list[str],
        tol_mul: float = 3.0,
        ransac: bool = True,
    ) -> tuple[list[BandMatch], list[str]]:
        """Hungarian assignment + optional RANSAC refinement.

        ``targets`` carries the (possibly auto-aligned) expected positions.
        ``tol_mul`` is the factor applied to each target's tolerance to
        decide the hard cost cutoff.
        """
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        from scipy.stats import linregress

        n_det = len(bands_with_rf)
        n_tmp = len(targets)
        if n_det == 0 or n_tmp == 0:
            return [], notes
        INF_COST = 1e6

        cost = np.full((n_det, n_tmp), INF_COST, dtype=float)
        for j, (_tb, target_rf, tol) in enumerate(targets):
            for i, (_band, rf) in enumerate(bands_with_rf):
                delta = abs(rf - target_rf)
                if delta <= tol_mul * tol:
                    cost[i, j] = delta / max(tol, 1e-4)

        if n_det >= n_tmp:
            row_ind, col_ind = linear_sum_assignment(cost)
        else:
            col_ind, row_ind = linear_sum_assignment(cost.T)

        initial: list[dict] = []
        for r, c in zip(row_ind, col_ind, strict=False):
            if cost[r, c] >= INF_COST:
                continue
            band, rf = bands_with_rf[r]
            tb, target_rf, tol = targets[c]
            initial.append({"det_idx": r, "band": band, "rf": rf, "tb": tb, "target_rf": target_rf, "tol": tol})

        if len(initial) < 3 or not ransac:
            missing = n_tmp - len(initial)
            if missing > 0:
                notes.append(f"{missing} template band(s) had no candidate within {tol_mul:.0f}× tolerance.")
            return [
                BandMatch(
                    band_id=str(m["band"].id),
                    template_band_order=m["tb"].band_order,
                    mw_kda=m["tb"].mw_kda,
                    position_y=m["band"].position_y,
                    rf=m["rf"],
                )
                for m in initial
            ], notes

        # RANSAC refinement on global log-linear fit.
        rf_arr = np.array([m["rf"] for m in initial], dtype=float)
        log_mw_arr = np.log10(np.array([m["tb"].mw_kda for m in initial], dtype=float))
        fit = linregress(rf_arr, log_mw_arr)
        predicted = fit.slope * rf_arr + fit.intercept
        residuals = np.abs(log_mw_arr - predicted)
        resid_threshold = max(0.05, 2.0 * float(np.std(residuals)))
        current_r2 = float(fit.rvalue**2)

        assigned_ids = {m["det_idx"] for m in initial}
        unassigned = [(i, band, rf) for i, (band, rf) in enumerate(bands_with_rf) if i not in assigned_ids]

        swaps = 0
        for k, m in enumerate(initial):
            if residuals[k] <= resid_threshold:
                continue
            target_rf = m["target_rf"]
            tol = m["tol"]
            best_gain = 0.0
            best_swap = None
            for idx, (u_idx, u_band, u_rf) in enumerate(unassigned):
                if abs(u_rf - target_rf) > tol_mul * tol:
                    continue
                trial = rf_arr.copy()
                trial[k] = u_rf
                trial_fit = linregress(trial, log_mw_arr)
                trial_r2 = float(trial_fit.rvalue**2)
                if trial_r2 - current_r2 > best_gain + 1e-6:
                    best_gain = trial_r2 - current_r2
                    best_swap = (idx, u_idx, u_band, u_rf)
            if best_swap is not None:
                idx, u_idx, u_band, u_rf = best_swap
                m["band"] = u_band
                m["rf"] = u_rf
                m["det_idx"] = u_idx
                rf_arr[k] = u_rf
                unassigned.pop(idx)
                fit = linregress(rf_arr, log_mw_arr)
                current_r2 = float(fit.rvalue**2)
                swaps += 1

        if swaps:
            notes.append(f"RANSAC rescued {swaps} outlier(s) by swapping with better in-window candidates.")
        missing = n_tmp - len(initial)
        if missing > 0:
            notes.append(f"{missing} template band(s) had no candidate within {tol_mul:.0f}× tolerance.")

        return [
            BandMatch(
                band_id=str(m["band"].id),
                template_band_order=m["tb"].band_order,
                mw_kda=m["tb"].mw_kda,
                position_y=m["band"].position_y,
                rf=m["rf"],
            )
            for m in initial
        ], notes

    @staticmethod
    def _candidate_to_ephemeral_band(candidate: dict, lane: Lane):
        """Wrap a profile-detected candidate into a duck-typed Band-like stub.

        The matcher and serialisers only touch a handful of attributes
        (``id``, ``position_y``, ``bbox_*``, ``intensity_peak``,
        ``peak_prominence``). A light object avoids DB writes until Save.
        """
        import uuid as _uuid

        class _EphemeralBand:
            __slots__ = (
                "id",
                "position_y",
                "bbox_x",
                "bbox_y",
                "bbox_width",
                "bbox_height",
                "intensity_peak",
                "peak_prominence",
                "width_px",
                "snr",
                "lane_id",
                "is_ephemeral",
            )

        eph = _EphemeralBand()
        eph.id = candidate.get("id") or f"ephemeral:{_uuid.uuid4()}"
        eph.position_y = int(candidate.get("position_y", 0))
        eph.bbox_x = int(candidate.get("bbox_x", lane.x))
        eph.bbox_y = int(candidate.get("bbox_y", max(lane.y, eph.position_y - 4)))
        eph.bbox_width = int(candidate.get("bbox_width", lane.width))
        eph.bbox_height = int(candidate.get("bbox_height", 8))
        eph.intensity_peak = float(candidate.get("intensity_peak", 0.0))
        eph.peak_prominence = float(candidate.get("peak_prominence", 0.0))
        eph.width_px = float(candidate.get("width_px", 0.0))
        eph.snr = float(candidate.get("snr", 0.0))
        eph.lane_id = lane.id
        eph.is_ephemeral = True
        return eph

    @staticmethod
    def _peak_intensity_for_band_id(bands, band_id: str) -> float | None:
        for b in bands:
            if str(b.id) == str(band_id):
                return float(b.intensity_peak) if b.intensity_peak is not None else None
        return None

    def _drop_bad_matches(
        self,
        matches: list[BandMatch],
        template_bands: list,
        r_squared: float | None,
    ) -> tuple[list[BandMatch], list[str]]:
        """Remove matches whose residual (or Rf-to-expected distance) is too
        large to plausibly be the real band. They become MISSING instead of
        "forced wrong label + flag".

        Two independent conditions (a match is dropped if EITHER fires):
        - |log10(MW) residual from the log-linear fit| > 0.15 (≈ 40% MW).
        - |rf − expected_rf| > 4× expected_rf_tolerance (way outside the
          trained variance window, so likely a different band).
        """
        import numpy as np
        from scipy.stats import linregress

        if len(matches) < 3:
            return matches, []

        tb_by_order = {tb.band_order: tb for tb in template_bands}
        rfs = np.array([m.rf for m in matches], dtype=float)
        log_mws = np.log10(np.array([m.mw_kda for m in matches], dtype=float))

        try:
            fit = linregress(rfs, log_mws)
            predicted = fit.slope * rfs + fit.intercept
            residuals = np.abs(log_mws - predicted)
        except Exception:
            return matches, []

        kept: list[BandMatch] = []
        dropped_labels: list[str] = []
        for i, m in enumerate(matches):
            residual_too_high = float(residuals[i]) > 0.15
            tb = tb_by_order.get(m.template_band_order)
            rf_too_far = False
            if tb is not None and tb.expected_rf is not None:
                tol = float(tb.expected_rf_tolerance or 0.05)
                if abs(m.rf - float(tb.expected_rf)) > 4 * tol:
                    rf_too_far = True
            if residual_too_high or rf_too_far:
                label = f"{m.mw_kda:g} kDa"
                dropped_labels.append(label)
            else:
                kept.append(m)

        warnings: list[str] = []
        if dropped_labels:
            warnings.append(
                f"Dropped {len(dropped_labels)} bad match(es) ({', '.join(dropped_labels)}) "
                "— no detected band close enough to the expected position. "
                "These slots stay MISSING; consider re-detecting this lane."
            )
        return kept, warnings

    def _pairwise_consistency_check(
        self,
        matches: list[BandMatch],
        template_bands: list,
    ) -> tuple[set[int], list[str]]:
        """Two independent cross-checks a single R² can miss.

        Rank preservation catches label swaps (e.g. 250 placed below 150),
        and triplet collinearity catches bands that drift from the local
        log-linear shape — together they subsume gap-consistency and
        odd/even parity (which proved mostly redundant in practice).

        Returns ``(suspect_indices, warnings)`` with indices into the
        input ``matches`` list.
        """
        import numpy as np

        suspect: set[int] = set()
        warnings: list[str] = []
        n = len(matches)
        if n < 3:
            return suspect, warnings

        sorted_pairs = sorted(enumerate(matches), key=lambda p: p[1].template_band_order)
        sorted_idx = [orig for orig, _ in sorted_pairs]
        sorted_m = [m for _, m in sorted_pairs]

        # Rank preservation — Rf must increase with template_band_order.
        rank_violations = 0
        for i in range(n - 1):
            if sorted_m[i].rf > sorted_m[i + 1].rf + 1e-6:
                suspect.add(sorted_idx[i])
                suspect.add(sorted_idx[i + 1])
                rank_violations += 1
        if rank_violations:
            warnings.append(
                f"Rank violation: {rank_violations} pair(s) have the higher-MW match below the lower-MW match (Rf inversion)."
            )

        # Triplet collinearity in (Rf, log10(MW)).
        bad_triplets = 0
        for i in range(1, n - 1):
            a, b, c = sorted_m[i - 1], sorted_m[i], sorted_m[i + 1]
            x_span = c.rf - a.rf
            if abs(x_span) < 1e-4:
                continue
            t = (b.rf - a.rf) / x_span
            log_a = float(np.log10(a.mw_kda))
            log_b = float(np.log10(b.mw_kda))
            log_c = float(np.log10(c.mw_kda))
            log_b_pred = log_a + t * (log_c - log_a)
            if abs(log_b - log_b_pred) > 0.1:  # ~26% MW deviation
                suspect.add(sorted_idx[i])
                bad_triplets += 1
        if bad_triplets:
            warnings.append(f"Triplet collinearity: {bad_triplets} match(es) deviate from the log-linear triplet line.")

        return suspect, warnings

    @staticmethod
    def _flag_matches(template: LadderTemplate, matches: list[BandMatch], r_squared: float | None) -> int:
        """Flag a match when the lane's R² is low OR when |Rf - expected_rf| exceeds tolerance."""
        flagged = 0
        template_band_by_order = {b.band_order: b for b in template.bands.all()}
        low_r_squared = (r_squared is not None) and (r_squared < 0.95)
        for m in matches:
            tb = template_band_by_order.get(m.template_band_order)
            rf_flagged = False
            if tb is not None and tb.expected_rf is not None:
                tolerance = tb.expected_rf_tolerance or 0.05
                if abs((m.rf or 0.0) - float(tb.expected_rf)) > float(tolerance):
                    rf_flagged = True
            m.flagged = rf_flagged or low_r_squared
            if m.flagged:
                flagged += 1
        return flagged

    @staticmethod
    def _serialize_match(m: BandMatch) -> dict:
        return {
            "band_id": m.band_id,
            "template_band_order": m.template_band_order,
            "mw_kda": m.mw_kda,
            "position_y": m.position_y,
            "rf": m.rf,
            "residual": getattr(m, "residual", None),
            "peak_intensity": getattr(m, "peak_intensity", None),
            "flagged": getattr(m, "flagged", False),
        }

    # ------------------------------------------------------------------
    # Save & Train (transactional)
    # ------------------------------------------------------------------

    def save_training(
        self,
        template: LadderTemplate,
        lanes_payload: list[dict],
        *,
        user=None,
    ) -> dict:
        """Create / update LadderCalibration rows for the given lanes, then
        run `learn_rf_patterns` for the template. Atomic.

        lanes_payload items: {lane_id, matches: [{template_band_order, band_id, rf, peak_intensity}, ...]}
        """
        if not lanes_payload:
            raise ValueError("lanes_payload is empty")

        created_or_updated: list[str] = []
        with transaction.atomic():
            for item in lanes_payload:
                lane_id = item["lane_id"]
                matches = item.get("matches", [])
                lane = Lane.objects.select_related("analysis").get(id=lane_id, lane_type="LADDER")
                analysis = lane.analysis
                if analysis is None:
                    raise ValueError(f"Lane {lane_id} has no analysis")

                # Compute R² from the provided matches.
                band_match_objs: list[BandMatch] = []
                for m in matches:
                    band_match_objs.append(
                        BandMatch(
                            band_id=str(m["band_id"]),
                            template_band_order=int(m["template_band_order"]),
                            mw_kda=float(m["mw_kda"]),
                            position_y=int(m["position_y"]),
                            rf=float(m["rf"]),
                        )
                    )
                calib_result = self.calibration_service.calibrate(lane=lane, template=template, matches=band_match_objs)

                ladder_x_position = int(lane.x + lane.width / 2)
                calibration, _created = LadderCalibration.objects.update_or_create(
                    analysis=analysis,
                    ladder_lane=lane,
                    defaults={
                        "template": template,
                        "ladder_x_position": ladder_x_position,
                        "method": calib_result.method or "LOG_LINEAR",
                        "coefficients": calib_result.coefficients or {},
                        "r_squared": float(calib_result.r_squared or 0.0),
                        "band_matches": [
                            {
                                "template_band_order": m["template_band_order"],
                                "band_id": m["band_id"],
                                "mw_kda": m["mw_kda"],
                                "position_y": m["position_y"],
                                "rf": m["rf"],
                                "peak_intensity": m.get("peak_intensity"),
                            }
                            for m in matches
                        ],
                        "matched_band_count": len(matches),
                        "created_by": user,
                    },
                )
                created_or_updated.append(str(calibration.id))

            # Run learning after all calibrations land.
            learn_result = self.learning_service.learn_rf_patterns(template=template)
            summary = self.learning_service.get_training_summary(template)

        logger.info(
            f"Studio: saved {len(created_or_updated)} calibrations + trained template {template.code}",
            user=getattr(user, "username", None),
            template_id=str(template.pk),
            updated_bands=learn_result["updated_bands"],
        )
        return {
            "calibration_ids": created_or_updated,
            "learning": learn_result,
            "summary": summary,
        }
