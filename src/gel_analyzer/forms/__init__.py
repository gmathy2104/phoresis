"""HTML forms for gel_analyzer (Tailwind-styled, no MDB5 widgets).

Exports the API serialization helpers so callers can do
``from gel_analyzer.forms import lane_to_dict``.
"""

from gel_analyzer.forms.analysis_forms import (
    GelAnalysisCreateForm,
    analysis_to_dict,
    band_to_dict,
    lane_to_dict,
)
from gel_analyzer.forms.comparison_forms import saved_comparison_to_dict

__all__ = [
    "GelAnalysisCreateForm",
    "analysis_to_dict",
    "band_to_dict",
    "lane_to_dict",
    "saved_comparison_to_dict",
]
