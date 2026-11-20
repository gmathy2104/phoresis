"""
Forms for GelImage management.

Provides:
- GelImageUploadForm: Form for uploading new gel images with metadata
- GelImageEditForm: Form for editing an image's gel type, assay and description
- AssayChoiceField: the assay select, its options grouped by gel type

The HTML templates provide the Tailwind styling (``phoresis_ui``): the forms keep Django's plain
widgets so they can pair with the raw inputs of ``images/upload.html``. The label and the help
text are on the fields for a page that renders them.
"""

from django import forms
from django.db.models import Q
from django.forms.models import ModelChoiceIterator

from gel_analyzer.models import GelAssay, GelImage

GEL_TYPE_EMPTY_LABEL = "-- Select gel type --"
ASSAY_EMPTY_LABEL = "-- Select assay --"
ASSAY_HELPER = "What this gel is read for. Only a purity assay (SDS-PAGE) reads the POI share as a purity."
GEL_TYPE_HELPER = "Leave empty to take the assay's gel type."
ALLOWED_EXTENSIONS = (".gel", ".scn", ".tiff", ".tif", ".png", ".jpg", ".jpeg")
ACCEPTED_FILES = ",".join(ALLOWED_EXTENSIONS)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB


class _AssayByGelTypeIterator(ModelChoiceIterator):
    """Yield the assays grouped under one ``<optgroup>`` per gel type.

    ``Select.optgroups`` treats a choice whose LABEL is a list as a group, so
    yielding ``(gel type label, [choice, ...])`` is all a group takes. Groups follow
    ``GelImage.GelType`` order and carry its labels as they are ("Western Blot");
    a gel type without an assay gets no group. No script filters the options:
    the server refuses an assay of another gel type (``GelImage.clean``).
    """

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        groups = {value: [] for value in GelImage.GelType.values}
        for assay in self.queryset:
            groups.setdefault(assay.gel_type, []).append(self.choice(assay))
        labels = dict(GelImage.GelType.choices)
        for gel_type, choices in groups.items():
            if choices:
                yield (labels.get(gel_type, gel_type), choices)


class AssayChoiceField(forms.ModelChoiceField):
    """A ``ModelChoiceField`` over ``GelAssay`` whose options are grouped by gel type."""

    iterator = _AssayByGelTypeIterator

    def label_from_instance(self, obj):
        # Only the edit form can offer an inactive assay: the one the image already has.
        return obj.name if obj.is_active else f"{obj.name} (inactive)"


class _GelTypeFromAssayMixin:
    """The gel type may be left empty: the assay's is taken.

    The two rules between the fields:
    - gel type empty + an assay → the assay's gel type;
    - gel type empty + no assay → an error on the gel type.
    An assay of another gel type than the image's is refused by the model's
    ``GelImage.clean()``, which the ModelForm runs with the submitted values and
    which raises on the ``assay`` field. Checking it here too would show the
    message twice when an edit keeps the image's old assay and changes its gel
    type: the field error drops the assay from ``cleaned_data``, the instance
    keeps its old one, and the model refuses the pair again.
    """

    def _prepare_gel_type_field(self):
        field = self.fields["gel_type"]
        field.required = False
        field.choices = [("", GEL_TYPE_EMPTY_LABEL)] + list(GelImage.GelType.choices)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("gel_type") or "gel_type" in self.errors:
            return cleaned_data
        assay = cleaned_data.get("assay")
        if assay is not None:
            cleaned_data["gel_type"] = assay.gel_type
        elif "assay" not in self.errors:
            self.add_error("gel_type", "Choose a gel type, or an assay to take its gel type from.")
        return cleaned_data


class GelImageUploadForm(_GelTypeFromAssayMixin, forms.ModelForm):
    """
    Form for uploading new gel images.

    Handles:
    - File upload with validation for allowed formats
    - Assay selection (required), grouped by gel type
    - Gel type selection (optional: taken from the assay when empty)
    - Optional description

    The HTML template provides Tailwind styling — the form stays minimal so it can
    pair with raw inputs in `images/upload.html`. Samples are named at the Lane
    level, not the image level, since a gel typically contains several samples.
    """

    assay = AssayChoiceField(
        queryset=GelAssay.objects.filter(is_active=True),
        required=True,
        empty_label=ASSAY_EMPTY_LABEL,
        label="Assay",
        help_text=ASSAY_HELPER,
    )

    class Meta:
        model = GelImage
        fields = ["original_file", "gel_type", "assay", "description"]
        # The page draws the file input itself, inside its drop zone (images/upload.html): the widget only names the
        # accepted formats for a page that would render it.
        labels = {"original_file": "Gel image file", "gel_type": "Gel type", "description": "Description"}
        help_texts = {
            "original_file": f"Supported formats: {', '.join(ALLOWED_EXTENSIONS)}",
            "gel_type": GEL_TYPE_HELPER,
            "description": "",
        }
        widgets = {
            "original_file": forms.FileInput(attrs={"accept": ACCEPTED_FILES}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional notes about this gel image..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prepare_gel_type_field()
        # A new GelImage carries the model default UNKNOWN, which the ModelForm takes as the
        # select's initial value: the page then submitted UNKNOWN, never empty, so "empty =
        # the assay's gel type" never applied and every assay was refused as "for another gel
        # type" unless the user changed the gel type by hand.
        if "gel_type" not in (kwargs.get("initial") or {}):
            self.initial["gel_type"] = ""

    def clean_original_file(self):
        """Validate file extension and size."""
        file = self.cleaned_data.get("original_file")
        if file:
            # Check file extension
            if not file.name.lower().endswith(ALLOWED_EXTENSIONS):
                raise forms.ValidationError(f"Unsupported file extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

            # Check file size (max 100MB)
            if file.size > MAX_UPLOAD_BYTES:
                raise forms.ValidationError(
                    f"File too large. Maximum size is 100MB, got {file.size / (1024 * 1024):.1f}MB."
                )

        return file


class GelImageEditForm(_GelTypeFromAssayMixin, forms.ModelForm):
    """
    Form for editing gel image metadata (not the file itself): its gel type,
    assay and description.

    The assay is optional here: images uploaded before assays existed have none
    (their purity gate falls back to the gel type). The select offers the active
    assays plus the one the image already has, even if it was deactivated since.
    """

    assay = AssayChoiceField(
        queryset=GelAssay.objects.filter(is_active=True),
        required=False,
        empty_label=ASSAY_EMPTY_LABEL,
        label="Assay",
        help_text=ASSAY_HELPER,
    )

    class Meta:
        model = GelImage
        fields = ["gel_type", "assay", "description"]
        labels = {"gel_type": "Gel type", "description": "Description"}
        help_texts = {"gel_type": GEL_TYPE_HELPER, "description": ""}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prepare_gel_type_field()
        offered = Q(is_active=True)
        if self.instance.assay_id is not None:
            offered |= Q(pk=self.instance.assay_id)
        self.fields["assay"].queryset = GelAssay.objects.filter(offered)
