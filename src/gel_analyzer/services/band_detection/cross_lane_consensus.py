"""Cross-lane consensus service — post-processing step that adds soft-vote bands
to lanes missing a consensus position found in ≥N other lanes of the gel."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import numpy as np

from phoresis_core.logging_config import get_logger

from .models import DetectedBand

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class CrossLaneConsensusParams:
    min_lane_support: float = 0.66
    anchor_min_support: float = 0.66
    y_tolerance_px: int = 5
    enable_smile_correction: bool = True
    soft_vote_min_snr: float = 0.5
    lane_type: Literal["sample", "ladder", "all"] = "sample"

    def validate(self) -> None:
        if not 0.5 <= self.min_lane_support <= 0.9:
            raise ValueError(f"min_lane_support out of range: {self.min_lane_support}")
        if not 0.5 <= self.anchor_min_support <= 0.9:
            raise ValueError(f"anchor_min_support out of range: {self.anchor_min_support}")
        if not 3 <= self.y_tolerance_px <= 20:
            raise ValueError(f"y_tolerance_px out of range: {self.y_tolerance_px}")
        if not 0.2 <= self.soft_vote_min_snr <= 2.0:
            raise ValueError(f"soft_vote_min_snr out of range: {self.soft_vote_min_snr}")
        if self.lane_type not in ("sample", "ladder", "all"):
            raise ValueError(f"lane_type out of range: {self.lane_type}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> CrossLaneConsensusParams:
        if not data:
            return cls()
        return cls(
            min_lane_support=float(data.get("min_lane_support", 0.66)),
            anchor_min_support=float(data.get("anchor_min_support", 0.66)),
            y_tolerance_px=int(data.get("y_tolerance_px", 5)),
            enable_smile_correction=bool(data.get("enable_smile_correction", True)),
            soft_vote_min_snr=float(data.get("soft_vote_min_snr", 0.5)),
            lane_type=str(data.get("lane_type", "sample")).lower(),
        )


@dataclass
class AnchorFit:
    y_mean: float
    n_lanes: int
    fit_kind: Literal["quadratic", "linear"]
    coefficients: list[float]


@dataclass
class ConsensusResult:
    run_id: UUID
    added_bands: list[DetectedBand]
    anchor_fits: list[AnchorFit]
    fallback_tier: int
    skipped_lanes_no_signal: list[int]
    consensus_positions_count: int
    duration_ms: float


class CrossLaneConsensus:
    """Cross-lane consensus + smile-correction pipeline (clustering, anchor fits,
    2D smile offset interpolation, fallback tier resolution).

    Task 7 adds clustering + smile correction primitives. Task 8 will add
    voting / soft-vote / run() orchestration.
    """

    def __init__(self, params: CrossLaneConsensusParams):
        self.params = params

    def _greedy_cluster(self, items, gap_px: int) -> list[list]:
        """Sort by y, walk, open a new cluster when gap > gap_px."""
        if not items:
            return []
        items_sorted = sorted(items, key=lambda b: b.y_observed)
        clusters = [[items_sorted[0]]]
        for it in items_sorted[1:]:
            if it.y_observed - clusters[-1][-1].y_observed > gap_px:
                clusters.append([it])
            else:
                clusters[-1].append(it)
        return clusters

    def _dedup_cluster(self, cluster):
        """Keep only one band per lane — the one closest to the provisional mean."""
        if not cluster:
            return cluster
        y_mean = float(np.mean([b.y_observed for b in cluster]))
        by_lane = {}
        for b in cluster:
            if b.lane_id not in by_lane or abs(b.y_observed - y_mean) < abs(by_lane[b.lane_id].y_observed - y_mean):
                by_lane[b.lane_id] = b
        return list(by_lane.values())

    def _fit_anchor(self, cluster) -> AnchorFit:
        """Fit delta_y = f(lane_center_x) for this anchor cluster."""
        if len(cluster) < 2:
            raise ValueError("Cannot fit anchor with <2 lanes")
        y_mean = float(np.mean([b.y_observed for b in cluster]))
        xs = np.array([b.lane_center_x for b in cluster], dtype=float)
        ys = np.array([b.y_observed - y_mean for b in cluster], dtype=float)
        if len(cluster) >= 3:
            coeffs = np.polyfit(xs, ys, 2).tolist()
            return AnchorFit(y_mean=y_mean, n_lanes=len(cluster), fit_kind="quadratic", coefficients=coeffs)
        else:
            coeffs = np.polyfit(xs, ys, 1).tolist()
            return AnchorFit(y_mean=y_mean, n_lanes=len(cluster), fit_kind="linear", coefficients=coeffs)

    def _eval_fit(self, fit: AnchorFit, lane_center_x: float) -> float:
        return float(np.polyval(fit.coefficients, lane_center_x))

    def _smile_offset(self, anchors: list[AnchorFit], lane_center_x: float, y_observed: float) -> float:
        """2D interpolation between anchor fits, linearly weighted by y-position."""
        if not anchors:
            return 0.0
        if len(anchors) == 1:
            return self._eval_fit(anchors[0], lane_center_x)
        sorted_anchors = sorted(anchors, key=lambda a: a.y_mean)
        if y_observed <= sorted_anchors[0].y_mean:
            return self._eval_fit(sorted_anchors[0], lane_center_x)
        if y_observed >= sorted_anchors[-1].y_mean:
            return self._eval_fit(sorted_anchors[-1], lane_center_x)
        for i in range(len(sorted_anchors) - 1):
            lower, upper = sorted_anchors[i], sorted_anchors[i + 1]
            if lower.y_mean <= y_observed <= upper.y_mean:
                span = upper.y_mean - lower.y_mean
                if span <= 0:
                    return self._eval_fit(lower, lane_center_x)
                w = (y_observed - lower.y_mean) / span
                d_low = self._eval_fit(lower, lane_center_x)
                d_up = self._eval_fit(upper, lane_center_x)
                return (1 - w) * d_low + w * d_up
        return 0.0

    def _resolve_fallback_tier(self, anchors: list[AnchorFit]) -> int:
        if not anchors:
            return 0
        if len(anchors) == 1:
            return 1
        return 2

    # ------------------------------------------------------------------
    # Task 8: voting + soft vote + run() orchestration
    # ------------------------------------------------------------------

    def _scoped_lanes(self, analysis):
        """Return lanes filtered by ``self.params.lane_type``.

        Values map to the ``Lane.LaneType`` enum (annotations.py). Default
        ``"sample"`` keeps the consensus honest on mixed gels — ladder bands
        (MW rungs) don't align y-positionally with sample bands, so mixing
        them dilutes the support denominator and pollutes the anchor clusters.
        """
        qs = analysis.lanes.all()
        if self.params.lane_type == "sample":
            return qs.filter(lane_type="SAMPLE")
        if self.params.lane_type == "ladder":
            return qs.filter(lane_type="LADDER")
        return qs

    def _collect_bands(self, analysis) -> list:
        """Load Band rows as lightweight items: (lane_id, lane_center_x, y_observed, band_obj)."""
        out = []
        for lane in self._scoped_lanes(analysis):
            lane_center_x = lane.x_center
            for b in lane.bands.all():

                class _I:
                    pass

                item = _I()
                item.lane_id = lane.id
                item.lane_center_x = lane_center_x
                item.y_observed = float(b.position_y)
                item.band = b
                out.append(item)
        return out

    def _build_anchors(self, items) -> list[AnchorFit]:
        """Greedy cluster + filter by ``anchor_min_support`` + dedup + fit."""
        n_total = len({it.lane_id for it in items})
        if n_total == 0:
            return []
        clusters = self._greedy_cluster(items, gap_px=25)
        anchors: list[AnchorFit] = []
        for cluster in clusters:
            distinct_lanes = {it.lane_id for it in cluster}
            support = len(distinct_lanes) / n_total
            if support < self.params.anchor_min_support:
                continue
            deduped = self._dedup_cluster(cluster)
            if len(deduped) < 2:
                continue
            anchors.append(self._fit_anchor(deduped))
        return anchors

    def _build_consensus_clusters(self, items, anchors: list[AnchorFit], tolerance: int) -> list[list]:
        """Apply smile correction to each item, then re-cluster with tight tolerance."""
        for it in items:
            delta = self._smile_offset(anchors, it.lane_center_x, it.y_observed) if anchors else 0.0
            it.y_corrected = it.y_observed - delta
        items_sorted = sorted(items, key=lambda i: i.y_corrected)
        if not items_sorted:
            return []
        clusters: list[list] = []
        current = [items_sorted[0]]
        for it in items_sorted[1:]:
            if it.y_corrected - current[-1].y_corrected > tolerance:
                clusters.append(current)
                current = [it]
            else:
                current.append(it)
        clusters.append(current)
        return clusters

    def _load_lane_crop(self, lane, analysis) -> np.ndarray:
        """Load the lane region from the gel image as a numpy array.

        Patched in tests; real implementation reads from Django storage.
        Uses ``original_file`` (the canonical ``GelImage`` file field).
        """
        from PIL import Image

        fh = analysis.gel_image.original_file.open("rb")
        try:
            arr = np.array(Image.open(fh).convert("RGB"))
        finally:
            fh.close()
        return arr[lane.y : lane.y + lane.height, lane.x : lane.x + lane.width]

    def _build_profile_from_crop(self, sub_crop, lane, sub_y_offset, params):
        """Build an ``IntensityProfile`` from a lane sub-crop (no Lane model required).

        Mirrors ``HybridDetector._build_profile_from_crop`` but uses the
        caller-supplied Lane instance (for x / width / y reference).
        """
        from .models import IntensityProfile

        gray = np.dot(sub_crop[..., :3], [0.299, 0.587, 0.114]) if sub_crop.ndim == 3 else sub_crop.astype(np.float64)

        margin_px = int(lane.width * (100 - params.profile_width_percent) / 200)
        x_start = max(0, margin_px)
        x_end = min(lane.width, lane.width - margin_px)
        if x_end <= x_start:
            x_start, x_end = 0, lane.width

        sub_h = sub_crop.shape[0]
        y_positions = list(range(lane.y + sub_y_offset, lane.y + sub_y_offset + sub_h))
        raw = [float(np.mean(gray[i, x_start:x_end])) for i in range(sub_h)]
        return IntensityProfile(
            y_positions=y_positions,
            raw_intensities=raw,
            lane_x=lane.x,
            lane_y=lane.y + sub_y_offset,
            lane_width=lane.width,
            lane_height=sub_h,
            profile_x_start=lane.x + x_start,
            profile_x_end=lane.x + x_end,
        )

    def _soft_vote_on_lane(self, lane, analysis, target_y: int, bg_type: str) -> DetectedBand | None:
        """Run a tight d1/d2 around ``target_y`` in a missing lane.

        Returns a ``DetectedBand`` with ``_lane_id`` and ``_hybrid_phase``
        annotations, or ``None`` when no peak is found.
        """
        from .derivative_detector import DerivativeDetector
        from .models import BandDetectionParams, BandDetectionSource, DetectedBand
        from .profile_processor import ProfileProcessor

        tol = self.params.y_tolerance_px
        y_lo = max(0, target_y - 2 * tol)
        y_hi = min(lane.y + lane.height, target_y + 2 * tol)
        if y_hi - y_lo < 8:
            return None

        lane_crop = self._load_lane_crop(lane, analysis)
        sub_start = max(0, y_lo - lane.y)
        sub_end = min(lane_crop.shape[0], y_hi - lane.y)
        if sub_end - sub_start < 8:
            return None

        sub_crop = lane_crop[sub_start:sub_end, :]
        invert_mode = "always" if bg_type == "light" else "never"
        d1d2_params = BandDetectionParams(
            min_snr=self.params.soft_vote_min_snr,
            threshold_factor=0.5,
            clahe_enabled=True,
            invert_profile=invert_mode,
        )
        profile = self._build_profile_from_crop(sub_crop, lane, sub_start, d1d2_params)
        if not profile.raw_intensities:
            return None
        try:
            profile = ProfileProcessor(d1d2_params).process(profile)
            peaks, _ = DerivativeDetector(d1d2_params).detect(profile)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"Soft vote failed on lane {lane.id} at y={target_y}: {exc}")
            return None
        if not peaks:
            return None

        # Pick the peak closest to the target_y.
        peak = min(peaks, key=lambda p: abs(p.y_position - target_y))
        bbox_y = max(y_lo, peak.y_position - tol)
        bbox_height = min(2 * tol, y_hi - bbox_y)
        if bbox_height < 1:
            return None

        band = DetectedBand(
            position_y=peak.y_position,
            bbox_x=lane.x,
            bbox_y=bbox_y,
            bbox_width=lane.width,
            bbox_height=bbox_height,
            confidence=min(peak.snr / 10.0, 0.6),
            detection_source=BandDetectionSource.HYBRID,
            intensity_peak=peak.height,
            peak_prominence=peak.prominence,
            peak_width_px=peak.width_px,
            snr=peak.snr,
        )
        band._hybrid_phase = "cross_lane_filled"
        band._lane_id = lane.id
        return band

    def _is_idempotent_conflict(self, lane, candidate_y: int) -> bool:
        """Return True if an existing band should reject a new candidate at ``candidate_y``."""
        tol = self.params.y_tolerance_px
        for existing in lane.bands.all():
            # Guard (a): proximity + consensus-provenance match.
            if abs(existing.position_y - candidate_y) < 3 * tol:
                metadata = existing.metadata or {}
                if metadata.get("hybrid_phase") == "cross_lane_filled":
                    return True
            # Guard (b): pixel overlap on Y.
            cand_top = candidate_y - tol
            cand_bot = candidate_y + tol
            ex_top = existing.bbox_y if existing.bbox_y is not None else existing.position_y
            ex_height = existing.bbox_height or 0
            ex_bot = ex_top + ex_height
            if max(cand_top, ex_top) < min(cand_bot, ex_bot):
                return True
        return False

    def _resolve_bg_type(self, analysis) -> str:
        """Determine global polarity for the gel image via the first lane's profile."""
        from .cv2_detector import CV2BandDetector
        from .cv2_params import CV2DetectionParams

        cv2_detector = CV2BandDetector(CV2DetectionParams())
        first_lane = analysis.lanes.filter(lane_type="SAMPLE").first()
        if first_lane is None:
            first_lane = analysis.lanes.first()
        if first_lane is None:
            return "dark"
        try:
            crop = self._load_lane_crop(first_lane, analysis)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"bg_type detection: failed to load crop ({exc})")
            return "dark"
        gray = np.mean(crop, axis=2) if crop.ndim == 3 else crop.astype(np.float64)
        if gray.size == 0:
            return "dark"
        profile = gray.mean(axis=1)
        return cv2_detector._detect_polarity(profile)

    def run(self, analysis, dry_run: bool = False) -> ConsensusResult:
        """Execute the full consensus pipeline for ``analysis``.

        Returns a :class:`ConsensusResult`. Emits bands into the DB only
        when ``dry_run=False``. Idempotent: re-running the same analysis
        yields the same total count, thanks to
        :meth:`_is_idempotent_conflict` guards.
        """
        self.params.validate()
        t0 = time.perf_counter()
        run_id = uuid.uuid4()

        # Step 1 — Collect existing bands.
        items = self._collect_bands(analysis)
        lanes_with_bands = {it.lane_id for it in items}
        if len(lanes_with_bands) < 3:
            logger.warning(f"[CLC] Only {len(lanes_with_bands)} lanes have bands; skipping consensus.")
            return ConsensusResult(
                run_id=run_id,
                added_bands=[],
                anchor_fits=[],
                fallback_tier=0,
                skipped_lanes_no_signal=[],
                consensus_positions_count=0,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        # Step 2 — Build anchors (smile correction).
        anchors = self._build_anchors(items) if self.params.enable_smile_correction else []
        fallback_tier = self._resolve_fallback_tier(anchors)
        tolerance_by_tier = {
            0: 15,
            1: 10,
            2: self.params.y_tolerance_px,
        }
        tolerance = tolerance_by_tier[fallback_tier]

        # Step 3 — Post-smile clustering.
        consensus_clusters = self._build_consensus_clusters(
            items,
            anchors,
            tolerance,
        )

        # Step 4 — Vote + Step 5 — Soft vote on missing lanes.
        n_total_lanes = self._scoped_lanes(analysis).count()
        all_lanes = list(self._scoped_lanes(analysis))
        consensus_positions: list[list] = []
        added_bands: list[DetectedBand] = []
        skipped: set[int] = set()
        bg_type = self._resolve_bg_type(analysis)

        for cluster in consensus_clusters:
            distinct = {it.lane_id for it in cluster}
            support = len(distinct) / n_total_lanes if n_total_lanes else 0.0
            if support < self.params.min_lane_support:
                continue
            consensus_positions.append(cluster)
            y_mean = float(np.mean([it.y_corrected for it in cluster]))

            for lane in all_lanes:
                if lane.id in distinct:
                    continue
                target_y = int(y_mean + self._smile_offset(anchors, lane.x_center, y_mean))
                if self._is_idempotent_conflict(lane, target_y):
                    continue
                band = self._soft_vote_on_lane(
                    lane,
                    analysis,
                    target_y,
                    bg_type,
                )
                if band is None:
                    skipped.add(lane.id)
                else:
                    added_bands.append(band)

        # Persist on apply.
        if not dry_run and added_bands:
            from gel_analyzer.models import Band

            to_create = []
            for b in added_bands:
                to_create.append(
                    Band(
                        lane_id=b._lane_id,
                        position_y=b.position_y,
                        bbox_x=b.bbox_x,
                        bbox_y=b.bbox_y,
                        bbox_width=b.bbox_width,
                        bbox_height=b.bbox_height,
                        confidence=b.confidence,
                        detection_source=Band.DetectionSource.HYBRID,
                        metadata={
                            "hybrid_phase": "cross_lane_filled",
                            "consensus_run_id": str(run_id),
                        },
                    )
                )
            Band.objects.bulk_create(to_create)

        return ConsensusResult(
            run_id=run_id,
            added_bands=added_bands,
            anchor_fits=anchors,
            fallback_tier=fallback_tier,
            skipped_lanes_no_signal=sorted(skipped),
            consensus_positions_count=len(consensus_positions),
            duration_ms=(time.perf_counter() - t0) * 1000,
        )


def serialize_consensus_result(result: ConsensusResult) -> dict:
    """JSON-safe dict form of a ConsensusResult (UUID -> str, Literal fine)."""
    return {
        "run_id": str(result.run_id),
        "added_bands": [
            {
                "lane_id": getattr(b, "_lane_id", None),
                "position_y": b.position_y,
                "bbox_x": b.bbox_x,
                "bbox_y": b.bbox_y,
                "bbox_width": b.bbox_width,
                "bbox_height": b.bbox_height,
                "confidence": b.confidence,
                "hybrid_phase": getattr(b, "_hybrid_phase", "cross_lane_filled"),
                "snr": b.snr,
                "peak_prominence": b.peak_prominence,
            }
            for b in result.added_bands
        ],
        "anchor_fits": [asdict(a) for a in result.anchor_fits],
        "fallback_tier": result.fallback_tier,
        "skipped_lanes_no_signal": result.skipped_lanes_no_signal,
        "consensus_positions_count": result.consensus_positions_count,
        "duration_ms": round(result.duration_ms, 1),
    }
