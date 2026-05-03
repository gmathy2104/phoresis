"""
MobileSAM service for band polygon refinement.

This module provides server-side MobileSAM inference:
- Encoder: Generates image embeddings
- Decoder: Converts bounding boxes to precise polygon masks

When SAM_BACKEND_ENABLED is True, the detection pipeline
automatically refines band polygons using the decoder service.
"""

try:
    from .decoder_service import MobileSAMDecoderService
    from .encoder_service import MobileSAMEncoderService
except ImportError:
    MobileSAMEncoderService = None
    MobileSAMDecoderService = None

__all__ = [
    "MobileSAMEncoderService",
    "MobileSAMDecoderService",
]
