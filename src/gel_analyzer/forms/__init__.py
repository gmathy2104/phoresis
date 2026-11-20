"""HTML forms for gel_analyzer (Tailwind-styled, no MDB5 widgets).

Image Forms:
- GelImageUploadForm: Upload a gel image with its assay, gel type and description
- GelImageEditForm: Edit an image's gel type, assay and description

Analysis Forms:
- GelAnalysisCreateForm: Create new analysis from image

Also exports the API serialization helpers so callers can do
``from gel_analyzer.forms import lane_to_dict``:
- lane_to_dict: Serialize Lane to dict for API
- band_to_dict: Serialize Band to dict for API
- analysis_to_dict: Serialize GelAnalysis to dict for API
- saved_comparison_to_dict: Serialize SavedComparison to dict for API
"""

from gel_analyzer.forms.analysis_forms import (
    GelAnalysisCreateForm,
    analysis_to_dict,
    band_to_dict,
    lane_to_dict,
)
from gel_analyzer.forms.comparison_forms import saved_comparison_to_dict
from gel_analyzer.forms.image_forms import GelImageEditForm, GelImageUploadForm

__all__ = [
    # Image forms
    "GelImageUploadForm",
    "GelImageEditForm",
    # Analysis forms
    "GelAnalysisCreateForm",
    "analysis_to_dict",
    "band_to_dict",
    "lane_to_dict",
    "saved_comparison_to_dict",
]
