"""CV2 vision-based band detection parameters with auto-calibration."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CV2DetectionParams:
    """Parameters for OpenCV adaptive-threshold band detection.

    All defaults are fallbacks — use ``auto_calibrate()`` to compute
    image-specific values.
    """

    # --- Adaptive threshold ---
    block_size: int = 35  # Neighborhood size (must be odd, >= 3)
    threshold_bias: float = 10.0  # C constant — lower = more sensitive

    # --- Morphology ---
    morph_kernel: int = 3  # Closing kernel (must be odd, >= 1)

    # --- Contour filtering ---
    min_band_area: int = 50  # Min contour area in px
    max_band_area: int = 5000  # Max contour area in px

    # --- Faint band boost (top-hat) ---
    faint_band_boost: bool = True
    tophat_radius: int = 25  # SE radius for top-hat

    # --- Preprocessing ---
    clahe_enabled: bool = True

    def __post_init__(self):
        # block_size must be odd and >= 3
        if self.block_size < 3:
            self.block_size = 3
        if self.block_size % 2 == 0:
            self.block_size += 1

        # morph_kernel must be odd and >= 1
        if self.morph_kernel < 1:
            self.morph_kernel = 1
        if self.morph_kernel % 2 == 0:
            self.morph_kernel += 1

        # Area sanity
        if self.min_band_area >= self.max_band_area:
            raise ValueError(f"min_band_area ({self.min_band_area}) must be < max_band_area ({self.max_band_area})")

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def from_dict(cls, data: dict | None) -> CV2DetectionParams:
        if not data:
            return cls()
        valid = {f.name for f in dataclasses.fields(cls)}
        filtered = {}
        for k, v in data.items():
            if k not in valid:
                continue
            target_type = next(f.type for f in dataclasses.fields(cls) if f.name == k)
            if target_type == "int":
                filtered[k] = int(v)
            elif target_type == "float":
                filtered[k] = float(v)
            elif target_type == "bool":
                filtered[k] = bool(v) if not isinstance(v, str) else v.lower() == "true"
            else:
                filtered[k] = v
        return cls(**filtered)

    @classmethod
    def auto_calibrate(cls, image: np.ndarray, lane_height: int) -> CV2DetectionParams:
        """Compute optimal parameters based on image characteristics."""
        img = image.ravel().astype(np.float64)

        is_16bit = image.dtype == np.uint16 or img.max() > 255

        p2 = float(np.percentile(img, 2))
        p98 = float(np.percentile(img, 98))
        trimmed_range = p98 - p2
        std_dev = float(np.std(img))

        block_size = max(11, min(99, int(lane_height * 0.05)))
        if block_size % 2 == 0:
            block_size += 1

        bias = max(2.0, min(25.0, trimmed_range / 65535.0 * 30.0)) if is_16bit else max(2.0, min(25.0, std_dev * 0.3))

        morph = max(1, min(9, int(lane_height * 0.008)))
        if morph % 2 == 0:
            morph += 1

        min_area = max(10, int(lane_height * 0.3))
        max_area = max(500, int(lane_height * 8.0))

        tophat = max(5, min(75, int(lane_height * 0.04)))

        params = cls(
            block_size=block_size,
            threshold_bias=round(bias, 1),
            morph_kernel=morph,
            min_band_area=min_area,
            max_band_area=max_area,
            tophat_radius=tophat,
        )

        logger.info(
            f"CV2 auto-calibrate: lane_height={lane_height}, "
            f"16bit={is_16bit}, std={std_dev:.1f}, block={params.block_size}, "
            f"bias={params.threshold_bias}, morph={params.morph_kernel}, "
            f"area=[{params.min_band_area}, {params.max_band_area}], "
            f"tophat={params.tophat_radius}"
        )
        return params
