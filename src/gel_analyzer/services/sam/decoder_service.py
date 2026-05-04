"""
MobileSAM Decoder Service for band polygon refinement.

Runs ONNX-based SAM decoder inference on the backend to convert
bounding box prompts into precise segmentation masks, which are
then converted to polygon coordinates.

This service is used by BandDetectionService to automatically
refine band polygons after peak detection.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
import onnxruntime as ort

from django.conf import settings

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class MobileSAMDecoderService:
    """
    Server-side MobileSAM decoder for polygon refinement.

    Takes pre-computed image embeddings and bounding box prompts
    to generate precise segmentation masks.

    Usage:
        service = MobileSAMDecoderService.get_instance()
        polygon = service.refine_band_polygon(
            embeddings, original_size, bbox
        )
    """

    _instance: MobileSAMDecoderService | None = None
    _session: ort.InferenceSession | None = None

    # Default model path (quantized for speed)
    DEFAULT_MODEL_PATH = "gel_analyzer/static/gel_analyzer/ml/sam/mobilesam_decoder_quant.onnx"

    # SAM input size constant
    SAM_INPUT_SIZE = 1024

    @classmethod
    def get_instance(cls, use_quantized: bool = True) -> MobileSAMDecoderService:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(use_quantized=use_quantized)
        return cls._instance

    def __init__(self, model_path: str | Path | None = None, use_quantized: bool = True):
        """
        Initialize the MobileSAM decoder.

        Args:
            model_path: Path to ONNX decoder model.
            use_quantized: If True, use quantized model for faster inference.
        """
        if model_path is None:
            # SRC_DIR (= BASE_DIR / "src") is the right anchor: source is COPY'd
            # to /app/src/... in the container, so static/ assets live at
            # /app/src/gel_analyzer/static/..., not /app/gel_analyzer/static/...
            src_dir = getattr(settings, "SRC_DIR", Path(settings.BASE_DIR) / "src")
            if use_quantized:
                model_path = src_dir / self.DEFAULT_MODEL_PATH
            else:
                model_path = src_dir / "gel_analyzer/static/gel_analyzer/ml/sam/mobilesam_decoder.onnx"

        self._model_path = Path(model_path)
        self._use_quantized = use_quantized
        self._load_model()

    def _load_model(self) -> None:
        """Load the ONNX decoder model."""
        if not self._model_path.exists():
            logger.error(f"MobileSAM decoder not found at {self._model_path}")
            raise FileNotFoundError(
                f"MobileSAM decoder not found at {self._model_path}. Download from MobileSAM-in-the-Browser repository."
            )

        logger.info(f"Loading MobileSAM decoder from {self._model_path}")

        # Configure ONNX Runtime session options
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 4

        # Create session - CPU provider is most portable
        providers = ["CPUExecutionProvider"]

        self._session = ort.InferenceSession(
            str(self._model_path),
            sess_options=sess_options,
            providers=providers,
        )

        logger.info(
            f"MobileSAM decoder loaded. "
            f"Inputs: {[i.name for i in self._session.get_inputs()]} "
            f"Outputs: {[o.name for o in self._session.get_outputs()]}"
        )

    def refine_band_polygon(
        self,
        image_embedding: np.ndarray,
        original_size: tuple[int, int],
        bbox: dict | list | tuple,
    ) -> list[list[int]]:
        """
        Refine a single band polygon using SAM decoder.

        Args:
            image_embedding: Pre-computed embedding tensor [1, 256, 64, 64].
            original_size: Original image (height, width).
            bbox: Bounding box as dict {x, y, width, height} or list [x, y, w, h].

        Returns:
            Polygon as list of [x, y] coordinate pairs.
        """
        if self._session is None:
            raise RuntimeError("SAM decoder not loaded")

        start_time = time.time()

        # Parse bbox
        if isinstance(bbox, dict):
            bx, by = bbox["x"], bbox["y"]
            bw, bh = bbox["width"], bbox["height"]
        else:
            bx, by, bw, bh = bbox

        # Prepare decoder inputs
        feeds = self._prepare_decoder_inputs(
            image_embedding,
            original_size,
            bx,
            by,
            bw,
            bh,
        )

        # Run decoder
        outputs = self._session.run(None, feeds)

        # Get mask (first output)
        mask_output = outputs[0]  # Shape: [1, 1, H, W] or [1, 4, H, W]

        # Take first mask (best IoU)
        mask = mask_output[0, 0] if mask_output.ndim == 4 else mask_output[0]

        # Convert mask to polygon (pass original_size for coordinate scaling)
        polygon = self._mask_to_polygon(mask, bx, by, bw, bh, original_size)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(f"SAM decoder: refined polygon in {elapsed_ms:.1f}ms")

        return polygon

    def refine_bands_batch(
        self,
        image_embedding: np.ndarray,
        original_size: tuple[int, int],
        bands: list[dict],
    ) -> list[dict]:
        """
        Refine multiple bands in batch.

        Args:
            image_embedding: Pre-computed embedding tensor [1, 256, 64, 64].
            original_size: Original image (height, width).
            bands: List of dicts with 'id' and 'bbox' keys.

        Returns:
            List of dicts with 'id', 'polygon', and 'success' keys.
        """
        results = []
        total_start = time.time()

        for band in bands:
            try:
                polygon = self.refine_band_polygon(
                    image_embedding,
                    original_size,
                    band["bbox"],
                )
                results.append(
                    {
                        "id": band["id"],
                        "polygon": polygon,
                        "success": True,
                    }
                )
            except Exception as e:
                logger.error(f"SAM refinement failed for band {band.get('id')}: {e}")
                results.append(
                    {
                        "id": band["id"],
                        "polygon": self._bbox_to_rectangle(band["bbox"]),
                        "success": False,
                        "error": str(e),
                    }
                )

        total_ms = (time.time() - total_start) * 1000
        logger.info(f"SAM batch: refined {len(bands)} bands in {total_ms:.1f}ms ({total_ms / len(bands):.1f}ms/band)")

        return results

    def _prepare_decoder_inputs(
        self,
        image_embedding: np.ndarray,
        original_size: tuple[int, int],
        bx: int,
        by: int,
        bw: int,
        bh: int,
    ) -> dict:
        """
        Prepare input tensors for SAM decoder.

        SAM decoder expects:
        - image_embeddings: [1, 256, 64, 64]
        - point_coords: [1, 2, 2] - bbox corners scaled to 1024
        - point_labels: [1, 2] - [2, 3] for bbox
        - mask_input: [1, 1, 256, 256] - zeros
        - has_mask_input: [1] - 0
        - orig_im_size: [2] - [H, W]
        """
        orig_h, orig_w = original_size

        # SAM preprocessing: resize to fit longest side = 1024, PRESERVING aspect ratio
        # Then pad to 1024x1024. Both X and Y must use the SAME scale factor!
        # Bug fix: was using different scale_x and scale_y which caused Y offset
        longest_side = max(orig_h, orig_w)
        scale = self.SAM_INPUT_SIZE / longest_side  # uniform scale for both axes

        # Bbox corners (top-left and bottom-right)
        x1, y1 = bx, by
        x2, y2 = bx + bw, by + bh

        scaled_x1 = x1 * scale
        scaled_y1 = y1 * scale
        scaled_x2 = x2 * scale
        scaled_y2 = y2 * scale

        logger.debug(
            f"SAM COORDS: original=({orig_w}x{orig_h}), scale={scale:.4f}, "
            f"bbox=({x1},{y1})-({x2},{y2}) → scaled=({scaled_x1:.1f},{scaled_y1:.1f})-({scaled_x2:.1f},{scaled_y2:.1f})"
        )

        # Point coordinates [1, 2, 2]
        point_coords = np.array(
            [[[scaled_x1, scaled_y1], [scaled_x2, scaled_y2]]],
            dtype=np.float32,
        )

        # Point labels: 2 = box top-left, 3 = box bottom-right
        point_labels = np.array([[2, 3]], dtype=np.float32)

        # Mask input (no prior mask)
        mask_input = np.zeros((1, 1, 256, 256), dtype=np.float32)

        # Has mask input flag
        has_mask_input = np.array([0], dtype=np.float32)

        # Original image size [H, W]
        orig_im_size = np.array([orig_h, orig_w], dtype=np.float32)

        # Ensure embedding is correct shape
        if image_embedding.ndim == 3:
            image_embedding = image_embedding[np.newaxis, ...]

        return {
            "image_embeddings": image_embedding.astype(np.float32),
            "point_coords": point_coords,
            "point_labels": point_labels,
            "mask_input": mask_input,
            "has_mask_input": has_mask_input,
            "orig_im_size": orig_im_size,
        }

    def _mask_to_polygon(
        self,
        mask: np.ndarray,
        bx: int,
        by: int,
        bw: int,
        bh: int,
        original_size: tuple[int, int] | None = None,
    ) -> list[list[int]]:
        """
        Convert binary mask to polygon using OpenCV contour finding.

        Following SAM2's approach: resize mask to original image dimensions
        BEFORE finding contours, so coordinates are directly in image space.

        Args:
            mask: Mask array (can be logits or probabilities).
            bx, by, bw, bh: Original bounding box in image coordinates.
            original_size: Original image (height, width) for mask resizing.

        Returns:
            Polygon as list of [x, y] coordinate pairs in original image space.
        """
        # Apply sigmoid if needed (logits > 20 indicates raw logits)
        if mask.max() > 20 or mask.min() < -20:
            mask = 1 / (1 + np.exp(-np.clip(mask, -20, 20)))

        # Get mask dimensions
        mask_h, mask_w = mask.shape[:2]
        mask_min, mask_max = float(mask.min()), float(mask.max())
        mask_mean = float(mask.mean())
        logger.info(
            f"SAM DEBUG: mask shape=({mask_h}x{mask_w}) [HxW], original_size={original_size}, "
            f"mask values: min={mask_min:.3f}, max={mask_max:.3f}, mean={mask_mean:.3f}, "
            f"bbox=({bx},{by},{bw},{bh})"
        )

        # CRITICAL FIX: Resize mask to original image dimensions BEFORE finding contours
        # This matches SAM2's postprocess_masks approach using F.interpolate(masks, orig_hw)
        if original_size is not None:
            orig_h, orig_w = original_size
            if (mask_h, mask_w) != (orig_h, orig_w):
                # Resize using bilinear interpolation (like SAM2)
                mask = cv2.resize(mask.astype(np.float32), (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
                logger.info(f"SAM FIX: Resized mask from ({mask_w}x{mask_h}) to ({orig_w}x{orig_h})")

        # Threshold to binary (now at original image resolution)
        binary = (mask > 0.5).astype(np.uint8) * 255

        # Find contours (coordinates are now in original image space!)
        contours, _ = cv2.findContours(
            binary,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        if not contours:
            logger.debug("No contours found, using bbox rectangle")
            return self._bbox_to_rectangle({"x": bx, "y": by, "width": bw, "height": bh})

        # Get largest contour
        largest_contour = max(contours, key=cv2.contourArea)

        if len(largest_contour) < 3:
            return self._bbox_to_rectangle({"x": bx, "y": by, "width": bw, "height": bh})

        # Simplify contour using Douglas-Peucker
        epsilon = 2.0
        simplified = cv2.approxPolyDP(largest_contour, epsilon, True)

        # Convert to list of [x, y] pairs (already in original image coordinates!)
        polygon = simplified.reshape(-1, 2).tolist()
        polygon = [[int(round(x)), int(round(y))] for x, y in polygon]

        # Ensure polygon has at least 3 points
        if len(polygon) < 3:
            return self._bbox_to_rectangle({"x": bx, "y": by, "width": bw, "height": bh})

        # Log polygon bounds vs bbox for debugging
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        logger.info(
            f"SAM POLYGON: bbox=({bx},{by})-({bx + bw},{by + bh}), "
            f"polygon bounds=({min(xs)},{min(ys)})-({max(xs)},{max(ys)}), "
            f"points={len(polygon)}"
        )

        return polygon

    def _bbox_to_rectangle(self, bbox: dict | list) -> list[list[int]]:
        """Convert bbox to rectangle polygon (fallback)."""
        if isinstance(bbox, dict):
            x, y = bbox["x"], bbox["y"]
            w, h = bbox["width"], bbox["height"]
        else:
            x, y, w, h = bbox

        return [
            [int(x), int(y)],
            [int(x + w), int(y)],
            [int(x + w), int(y + h)],
            [int(x), int(y + h)],
        ]

    @property
    def is_loaded(self) -> bool:
        """Check if decoder is loaded."""
        return self._session is not None
