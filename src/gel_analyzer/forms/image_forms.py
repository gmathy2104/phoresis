"""Forms for GelImage management."""

from django import forms

from gel_analyzer.models import GelImage


class GelImageUploadForm(forms.ModelForm):
    """Upload form. The HTML template provides Tailwind styling — we keep the form
    minimal so it can pair with raw inputs in `images/upload.html`."""

    class Meta:
        model = GelImage
        fields = ["original_file", "gel_type", "description"]

    def clean_original_file(self):
        f = self.cleaned_data.get("original_file")
        if not f:
            return f
        allowed = (".gel", ".scn", ".tiff", ".tif", ".png", ".jpg", ".jpeg")
        if not f.name.lower().endswith(allowed):
            raise forms.ValidationError(f"Unsupported file extension. Allowed: {', '.join(allowed)}")
        return f
