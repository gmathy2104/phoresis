"""
Band Detection Service Package.

Chromatography-inspired band detection for gel electrophoresis images
using derivative-based (d1/d2 zero-crossing) peak analysis.

Main Components:
- BandDetectionService: Orchestrates the full detection pipeline
- BandDetectionParams: User-configurable detection parameters
- IntensityProfileExtractor: Extracts 1D intensity from lane regions
- ProfileProcessor: Savitzky-Golay smoothing, background subtraction, derivative computation
- DerivativeDetector: d1/d2 zero-crossing peak detection (primary detection engine)
- BandGeometryBuilder: Creates band bounding boxes and polygons

Legacy Components (ladder-guided detection only):
- PeakDetector: scipy.signal.find_peaks (used only by _detect_ladder_guided)
- PeakIntegrator: boundary-centric integration (UNPLUGGED)

Usage:
    from gel_analyzer.services.band_detection import (
        BandDetectionService,
        BandDetectionParams,
    )

    params = BandDetectionParams(d2_significance_factor=2.0, min_snr=1.5)
    service = BandDetectionService(params)

    # Preview mode
    result = service.detect_bands_in_lane(lane, image)

    # Save mode
    result = service.detect_and_save(lane, image, user)

    # Bulk detection
    results = service.detect_all_lanes(analysis, user, save_results=True)
"""

from .cross_lane_consensus import (
    AnchorFit,
    ConsensusResult,
    CrossLaneConsensus,
    CrossLaneConsensusParams,
    serialize_consensus_result,
)
from .derivative_detector import DerivativeDetector
from .geometry_builder import BandGeometryBuilder
from .hybrid_detector import GapRegion, HybridDetector
from .hybrid_params import HybridDetectionParams
from .models import (
    REFERENCE_HEIGHT,
    BackgroundMethod,
    BandDetectionParams,
    BandDetectionResult,
    BandDetectionSource,
    DetectedBand,
    DetectedPeak,
    IntensityProfile,
)
from .peak_detector import PeakDetector
from .peak_integrator import (
    BoundaryType,
    IntegratedBand,
    IntegrationBoundary,
    PeakIntegrator,
    integrated_bands_to_peaks,
)
from .profile_extractor import IntensityProfileExtractor
from .profile_processor import ProfileProcessor, estimate_noise
from .service import (
    BandDetectionService,
    detect_bands_bulk,
    detect_bands_preview,
)

__all__ = [
    # Constants
    "REFERENCE_HEIGHT",
    # Enums
    "BackgroundMethod",
    "BandDetectionSource",
    # Dataclasses
    "BandDetectionParams",
    "IntensityProfile",
    "DetectedPeak",
    "DetectedBand",
    "BandDetectionResult",
    # Pipeline components
    "IntensityProfileExtractor",
    "ProfileProcessor",
    "estimate_noise",
    "PeakDetector",
    "BoundaryType",
    "IntegrationBoundary",
    "IntegratedBand",
    "PeakIntegrator",
    "integrated_bands_to_peaks",
    "BandGeometryBuilder",
    "DerivativeDetector",
    # Service
    "BandDetectionService",
    # Convenience functions
    "detect_bands_preview",
    "detect_bands_bulk",
    # Hybrid detection
    "HybridDetectionParams",
    "HybridDetector",
    "GapRegion",
    # Cross-lane consensus
    "CrossLaneConsensus",
    "CrossLaneConsensusParams",
    "ConsensusResult",
    "AnchorFit",
    "serialize_consensus_result",
]
