"""
GelAnalyzer services package.

Services:
- GelFileHandler: File format detection and conversion
- MobileSAMEncoderService: SAM encoder for band polygon refinement
- TemplateLearningService: Learn Rf patterns from calibrations
- DensitometryService: Quantitative band analysis
- GelAnalysisReportBuilder: Word report generation
- ReportDataCollector: Report data collection
"""

from .densitometry import (
    DensitometryNormalizer,
    DensitometryParams,
    DensitometryService,
    PeakIntegrator,
    PurityCalculator,
)
from .file_handler import GelFileHandler
from .sam import MobileSAMDecoderService, MobileSAMEncoderService
from .scn_parser import SCNParseError, SCNParser
from .studio import StudioService
from .template_learning import TemplateLearningService

# Ported incrementally — re-enable as later Phase 2 tasks land:
# from .report import (                                             # deferred to Phase 4
#     GelAnalysisReportBuilder,
#     ReportDataCollector,
# )

__all__ = [
    "GelFileHandler",
    "SCNParser",
    "SCNParseError",
    # Densitometry
    "DensitometryService",
    "DensitometryParams",
    "PeakIntegrator",
    "DensitometryNormalizer",
    "PurityCalculator",
    # SAM
    "MobileSAMEncoderService",
    "MobileSAMDecoderService",
    # Template learning
    "TemplateLearningService",
    # Studio
    "StudioService",
    # # Reports
    # 'GelAnalysisReportBuilder',
    # 'ReportDataCollector',
]
