"""
MobileSAM Encoder Service for band polygon refinement.

Generates image embeddings server-side using MobileSAM's lightweight
encoder. Embeddings are cached and sent to browser for decoder inference.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch

from django.conf import settings
from django.core.cache import cache

from phoresis_core.logging_config import get_logger

if TYPE_CHECKING:
    from gel_analyzer.models import GelImage

logger = get_logger(__name__)


class MobileSAMEncoderService:
    """
    Server-side MobileSAM encoder with singleton pattern and caching.

    Generates image embeddings that can be used by the browser-side
    decoder to produce precise band segmentation masks given bounding
    box prompts.

    Usage:
        service = MobileSAMEncoderService.get_instance()
        embeddings = service.encode_image(image_array)
    """

    _instance: MobileSAMEncoderService | None = None
    _model = None
    _predictor = None
    _device = None

    # Default model path
    DEFAULT_MODEL_PATH = "gel_analyzer/static/gel_analyzer/ml/sam/mobile_sam.pt"

    @classmethod
    def get_instance(cls) -> MobileSAMEncoderService:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, model_path: str | Path | None = None):
        """
        Initialize the MobileSAM encoder.

        Args:
            model_path: Path to mobile_sam.pt weights file.
                       Defaults to static/gel_analyzer/ml/sam/mobile_sam.pt
        """
        if model_path is None:
            model_path = Path(settings.BASE_DIR) / self.DEFAULT_MODEL_PATH

        self._model_path = Path(model_path)
        self._load_model()

    def _load_model(self) -> None:
        """Load the MobileSAM model."""
        try:
            from mobile_sam import SamPredictor, sam_model_registry
        except ImportError as e:
            logger.error(f"MobileSAM not installed: {e}")
            raise ImportError(
                "MobileSAM is required. Install with: pip install git+https://github.com/ChaoningZhang/MobileSAM.git"
            ) from e

        if not self._model_path.exists():
            logger.error(f"MobileSAM weights not found at {self._model_path}")
            raise FileNotFoundError(
                f"MobileSAM weights not found at {self._model_path}. "
                "Download from: https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt"
            )

        # Determine device (CPU for compatibility, MPS for M1/M2 Macs)
        if torch.backends.mps.is_available():
            self._device = torch.device("mps")
            logger.info("Using MPS (Apple Silicon) for MobileSAM")
        elif torch.cuda.is_available():
            self._device = torch.device("cuda")
            logger.info("Using CUDA for MobileSAM")
        else:
            self._device = torch.device("cpu")
            logger.info("Using CPU for MobileSAM")

        # Load model
        logger.info(f"Loading MobileSAM from {self._model_path}")
        self._model = sam_model_registry["vit_t"](checkpoint=str(self._model_path))
        self._model.to(self._device)
        self._model.eval()

        # Create predictor
        self._predictor = SamPredictor(self._model)
        logger.info("MobileSAM encoder loaded successfully")

    def encode_image(self, image: np.ndarray) -> dict:
        """
        Generate image embeddings for browser-side decoder.

        Args:
            image: RGB image array (H, W, 3) with uint8 values [0-255].

        Returns:
            Dictionary containing:
            - image_embedding: Base64-encoded embedding tensor
            - original_size: [height, width] of input image
            - input_size: [height, width] after preprocessing
            - embedding_shape: Shape of the embedding tensor
        """
        if self._predictor is None:
            raise RuntimeError("MobileSAM model not loaded")

        # Ensure RGB format
        if len(image.shape) == 2:
            # Grayscale - convert to RGB
            image = np.stack([image] * 3, axis=-1)
        elif image.shape[2] == 4:
            # RGBA - drop alpha
            image = image[:, :, :3]

        # Set image (this runs the encoder)
        self._predictor.set_image(image)

        # Get embedding
        embedding = self._predictor.get_image_embedding()

        # Convert to numpy and encode as base64 for JSON transport
        embedding_np = embedding.cpu().numpy()
        embedding_bytes = embedding_np.tobytes()
        embedding_b64 = base64.b64encode(embedding_bytes).decode("ascii")

        return {
            "image_embedding": embedding_b64,
            "original_size": list(image.shape[:2]),  # [H, W]
            "input_size": list(self._predictor.input_size),  # [H, W] after resize
            "embedding_shape": list(embedding_np.shape),  # [1, 256, 64, 64] typically
            "dtype": str(embedding_np.dtype),  # 'float32'
        }

    def get_cached_embeddings(
        self,
        gel_image: GelImage,
        force_refresh: bool = False,
    ) -> dict:
        """
        Get or generate cached embeddings for a gel image.

        Args:
            gel_image: GelImage model instance.
            force_refresh: If True, regenerate even if cached.

        Returns:
            Embedding dictionary.
        """
        cache_key = f"sam_embeddings_{gel_image.pk}"
        cache_timeout = 24 * 60 * 60  # 24 hours

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                logger.debug(f"Using cached SAM embeddings for image {gel_image.pk}")
                return cached

        # Load image using class method
        from gel_analyzer.services.file_handler import GelFileHandler

        image_array = GelFileHandler.load_image_as_array(gel_image)

        if image_array is None:
            raise ValueError(f"Could not load image for {gel_image.pk}")

        # Generate embeddings
        logger.info(f"Generating SAM embeddings for image {gel_image.pk}")
        embeddings = self.encode_image(image_array)

        # Cache
        cache.set(cache_key, embeddings, timeout=cache_timeout)
        logger.info(f"Cached SAM embeddings for image {gel_image.pk}")

        return embeddings

    def clear_cached_embeddings(self, gel_image: GelImage) -> bool:
        """
        Clear cached embeddings for an image.

        Args:
            gel_image: GelImage model instance.

        Returns:
            True if cache was cleared.
        """
        cache_key = f"sam_embeddings_{gel_image.pk}"
        cache.delete(cache_key)
        logger.info(f"Cleared SAM embeddings cache for image {gel_image.pk}")
        return True

    @property
    def is_loaded(self) -> bool:
        """Check if the model is loaded."""
        return self._predictor is not None

    @property
    def device(self) -> str:
        """Get the device being used."""
        return str(self._device) if self._device else "not loaded"
