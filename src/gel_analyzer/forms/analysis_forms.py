"""Forms for GelAnalysis."""

from django import forms

from gel_analyzer.models import GelAnalysis


class GelAnalysisCreateForm(forms.ModelForm):
    class Meta:
        model = GelAnalysis
        fields = ["name", "notes"]
