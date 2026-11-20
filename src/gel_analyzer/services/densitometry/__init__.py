"""
Densitometry services for quantitative gel band analysis.

This package provides:
- DensitometryService: Main orchestrator for densitometry analysis
- PeakIntegrator: Gaussian fitting and peak integration
- DensitometryNormalizer: Relative quantification (lane/gel total, loading control)
- PurityCalculator: POI purity calculations
- DensitometryExporter: CSV/PDF export utilities
- AdvancedPeakDetector: Automatic peak detection from profiles
- PeakDeconvolutionService: Multi-Gaussian deconvolution
- PeakMatchingService: Match peaks to existing bands

Usage:
    from gel_analyzer.services.densitometry import (
        DensitometryService,
        DensitometryParams,
        AdvancedPeakDetector,
        PeakDetectionParams,
    )

    service = DensitometryService()
    result = service.analyze_lane(lane, image)
"""

from .advanced_peak_detector import AdvancedPeakDetector, detect_peaks_in_profile
from .models import (
    DensitometryAnalysisResult,
    DensitometryParams,
    DetectedPeakWithMatch,
    LaneDensitometryResultData,
    NormalizationMethod,
    PeakDetectionParams,
    PeakDetectionResult,
    PeakIntegrationResult,
)
from .normalizer import DensitometryNormalizer, NormalizationRefused
from .peak_deconvolution import PeakDeconvolutionService
from .peak_integrator import PeakIntegrator
from .peak_matching import PeakMatchingService, match_peaks_and_bands
from .purity_calculator import PurityCalculator
from .service import DensitometryService

__all__ = [
    # Main service
    "DensitometryService",
    # Supporting services
    "PeakIntegrator",
    "DensitometryNormalizer",
    "PurityCalculator",
    # Peak detection services
    "AdvancedPeakDetector",
    "detect_peaks_in_profile",
    "PeakDeconvolutionService",
    "PeakMatchingService",
    "match_peaks_and_bands",
    # Dataclasses
    "DensitometryParams",
    "PeakDetectionParams",
    "DetectedPeakWithMatch",
    "PeakDetectionResult",
    "PeakIntegrationResult",
    "LaneDensitometryResultData",
    "DensitometryAnalysisResult",
    "NormalizationMethod",
    # Refusal
    "NormalizationRefused",
]
