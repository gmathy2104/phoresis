"""Parameters for hybrid band detection (CV2 primary + d1/d2 gap-fill)."""

from __future__ import annotations

from dataclasses import dataclass

from .cv2_params import CV2DetectionParams
from .models import BandDetectionParams


def _lerp(sensitivity: int, low_val: float, mid_val: float, high_val: float) -> float:
    """Linear interpolation across sensitivity 1-5-10 anchor points."""
    if sensitivity <= 5:
        t = (sensitivity - 1) / 4.0
        return low_val + t * (mid_val - low_val)
    else:
        t = (sensitivity - 5) / 5.0
        return mid_val + t * (high_val - mid_val)


@dataclass
class HybridDetectionParams:
    """
    Simplified parameters for hybrid band detection.

    Scientists interact with:
    - sensitivity (1-10): single slider controlling detection aggressiveness
    - faint_bands (bool): toggle for detecting faint/shoulder bands in gaps
    - large_bands (bool): toggle for handling large/diffuse bands

    These map internally to CV2DetectionParams and BandDetectionParams.
    """

    sensitivity: int = 5
    faint_bands: bool = True
    large_bands: bool = True
    split_wide_bands: bool = True
    mask_loading_wells: bool = True
    adaptive_threshold: bool = True

    # Floor at 15px = default derivative_window. Below this, d1/d2 cannot
    # compute meaningful derivatives and gap-fill returns []. This keeps
    # min_gap_size_px and derivative_window in sync.
    MIN_GAP_FLOOR_PX = 15

    def __post_init__(self):
        self.sensitivity = max(1, min(10, self.sensitivity))

    @property
    def min_gap_size_px(self) -> int:
        """Minimum gap size in pixels for d1/d2 gap-fill analysis.

        Floored at 15px (= default derivative_window).
        """
        raw = round(_lerp(self.sensitivity, 30, 20, 10))
        return max(self.MIN_GAP_FLOOR_PX, raw)

    def to_cv2_params(self) -> CV2DetectionParams:
        """Map sensitivity + toggles to CV2 detection parameters.

        CV2DetectionParams only exposes `tophat_radius` (not `rolling_ball_radius`)
        and does NOT have `max_band_width_px`. The "large bands" toggle therefore
        only affects `max_band_area` and `tophat_radius`.
        """
        threshold_bias = _lerp(self.sensitivity, 18.0, 10.0, 4.0)

        max_band_area = 5000
        tophat_radius = 25

        if self.large_bands:
            max_band_area = round(max_band_area * 2)
            tophat_radius = round(tophat_radius * 1.3)

        return CV2DetectionParams(
            threshold_bias=round(threshold_bias, 1),
            max_band_area=max_band_area,
            tophat_radius=tophat_radius,
            faint_band_boost=self.faint_bands,
            clahe_enabled=True,
        )

    def to_derivative_params(self) -> BandDetectionParams:
        """Map sensitivity + toggles to d1/d2 detection parameters."""
        min_snr = _lerp(self.sensitivity, 5.0, 2.0, 0.5)

        threshold_factor = 1.5
        d2_significance_factor = 1.5

        if self.faint_bands:
            threshold_factor *= 0.6
            d2_significance_factor *= 0.7

        return BandDetectionParams(
            min_snr=round(min_snr, 1),
            threshold_factor=round(threshold_factor, 2),
            d2_significance_factor=round(d2_significance_factor, 2),
            clahe_enabled=True,
        )

    def to_dict(self) -> dict:
        return {
            "sensitivity": self.sensitivity,
            "faint_bands": self.faint_bands,
            "large_bands": self.large_bands,
            "split_wide_bands": self.split_wide_bands,
            "mask_loading_wells": self.mask_loading_wells,
            "adaptive_threshold": self.adaptive_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> HybridDetectionParams:
        if not data:
            return cls()
        return cls(
            sensitivity=int(data.get("sensitivity", 5)),
            faint_bands=bool(data.get("faint_bands", True)),
            large_bands=bool(data.get("large_bands", True)),
            split_wide_bands=bool(data.get("split_wide_bands", True)),
            mask_loading_wells=bool(data.get("mask_loading_wells", True)),
            adaptive_threshold=bool(data.get("adaptive_threshold", True)),
        )
