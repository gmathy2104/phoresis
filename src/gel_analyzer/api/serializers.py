"""
DRF Serializers for Gel Analyzer API.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from django.db import transaction

from gel_analyzer.models import (
    Band,
    DensitometryJob,
    DensitometryResult,
    GelAnalysis,
    GelImage,
    LadderBandDefinition,
    LadderTemplate,
    Lane,
    MWMarker,
    ProteinQuantCalibration,
    ProteinQuantCalibrationPoint,
    SavedComparison,
)
from gel_analyzer.services.lane_geometry.shape import GeometryRefused, normalize_lane_write
from gel_analyzer.services.quantification.band_type_change import BandTypeRefused, apply_band_type, check_band_type

# =============================================================================
# GelImage Serializers
# =============================================================================


def _refuse_gel_type_off_assay(attrs, instance):
    """400 on ``gel_type`` when it would leave the image's assay on another gel type.

    The API does not set an assay (an image uploaded through it has none and
    falls back to its gel type for the purity gate); it must not break the pair
    the upload or edit page set. DRF never runs ``GelImage.clean()``, hence this.
    """
    if instance is None or "gel_type" not in attrs or instance.assay_id is None:
        return attrs
    if attrs["gel_type"] != instance.assay.gel_type:
        raise serializers.ValidationError(
            {
                "gel_type": (
                    f"This image's assay ({instance.assay.name}) is for "
                    f"{instance.assay.get_gel_type_display()} gels; change the assay on the image's edit page first."
                )
            }
        )
    return attrs


class GelImageListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for GelImage list views.

    Also the serializer of ``GelImageViewSet.partial_update``: a PATCH of
    ``gel_type`` lands here.
    """

    thumbnail_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = GelImage
        fields = [
            "id",
            "original_filename",
            "file_format",
            "gel_type",
            "width",
            "height",
            "bit_depth",
            "thumbnail_url",
            "uploaded_by",
            "uploaded_by_name",
            "uploaded_at",
        ]

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_uploaded_by_name(self, obj):
        return str(obj.uploaded_by) if obj.uploaded_by else None

    def validate(self, attrs):
        return _refuse_gel_type_off_assay(super().validate(attrs), self.instance)


class GelImageDetailSerializer(serializers.ModelSerializer):
    """Full serializer for GelImage with Azure-safe URLs."""

    original_file_url = serializers.SerializerMethodField()
    display_file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    analysis_count = serializers.SerializerMethodField()

    class Meta:
        model = GelImage
        fields = [
            "id",
            "original_filename",
            "file_format",
            "file_size_bytes",
            "gel_type",
            "description",
            "width",
            "height",
            "bit_depth",
            "original_file_url",
            "display_file_url",
            "thumbnail_url",
            "scanner_metadata",
            "uploaded_by",
            "uploaded_by_name",
            "analysis_count",
            "uploaded_at",
            "updated_at",
        ]
        # file_size_bytes is filled by the upload pipeline, description is editable
        read_only_fields = ["file_size_bytes"]

    @extend_schema_field(OpenApiTypes.URI)
    def get_original_file_url(self, obj):
        return obj.original_file.url if obj.original_file else None

    @extend_schema_field(OpenApiTypes.URI)
    def get_display_file_url(self, obj):
        return obj.display_file.url if obj.display_file else None

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_uploaded_by_name(self, obj):
        return str(obj.uploaded_by) if obj.uploaded_by else None

    @extend_schema_field(OpenApiTypes.INT)
    def get_analysis_count(self, obj):
        return obj.analyses.count()

    def validate(self, attrs):
        return _refuse_gel_type_off_assay(super().validate(attrs), self.instance)


class GelImageUploadSerializer(serializers.ModelSerializer):
    """Serializer for GelImage upload (multipart).

    No assay: an image uploaded through the API has none, and its purity gate
    falls back to its gel type (``signals.lane_measures_purity``).
    """

    class Meta:
        model = GelImage
        fields = ["id", "original_file", "gel_type"]
        read_only_fields = ["id"]


# =============================================================================
# Band Serializers
# =============================================================================


class QuantPointSerializer(serializers.ModelSerializer):
    """Nested serializer for a band's quantification calibration point."""

    class Meta:
        model = ProteinQuantCalibrationPoint
        fields = ("load_amount", "load_unit", "is_excluded_from_fit", "role")
        read_only_fields = ("role",)


def _validate_band_quant_point(attrs: dict, instance) -> dict:
    """Shared validation for BandSerializer and BandWriteSerializer: the band's resulting type against its quant_point.

    The rule is ``check_band_type`` (``services/quantification/band_type_change.py``), shared with the editor's band
    endpoints: CALIBRATION needs a quant_point, given or stored, in the active calibration's unit.
    """
    try:
        check_band_type(
            instance,
            attrs.get("band_type", getattr(instance, "band_type", None)),
            attrs.get("quant_point"),
            lane=attrs.get("lane"),
        )
    except BandTypeRefused as refusal:
        raise serializers.ValidationError(str(refusal)) from refusal
    return attrs


class BandSerializer(serializers.ModelSerializer):
    """Serializer for Band — includes polygon, bbox, and intensities."""

    bbox = serializers.SerializerMethodField()
    corrected_area = serializers.FloatField(
        source="densitometry.corrected_area", read_only=True, allow_null=True, required=False
    )
    estimated_amount = serializers.FloatField(
        source="densitometry.estimated_amount", read_only=True, allow_null=True, required=False
    )
    estimated_amount_unit = serializers.CharField(
        source="densitometry.estimated_amount_unit", read_only=True, allow_null=True, required=False
    )
    estimated_amount_range = serializers.CharField(
        source="densitometry.estimated_amount_range", read_only=True, allow_null=True, required=False
    )
    quant_point = QuantPointSerializer(required=False, allow_null=True)

    class Meta:
        model = Band
        fields = [
            "id",
            "lane",
            "band_type",
            "band_number",
            "detection_source",
            "confidence",
            "position_y",
            "polygon",
            "bbox",
            "estimated_mw_kda",
            "mw_estimation_method",
            "intensity_raw",
            "intensity_peak",
            "intensity_normalized",
            "area_pixels",
            "label",
            "notes",
            "metadata",
            "created_at",
            "updated_at",
            "corrected_area",
            "estimated_amount",
            "estimated_amount_unit",
            "estimated_amount_range",
            "quant_point",
        ]
        # Audit + provenance fields are server-managed; surface them but keep RO
        read_only_fields = [
            "band_number",
            "confidence",
            "mw_estimation_method",
            "metadata",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_bbox(self, obj):
        if obj.bbox_x is not None:
            return {
                "x": obj.bbox_x,
                "y": obj.bbox_y,
                "width": obj.bbox_width,
                "height": obj.bbox_height,
            }
        return None

    def validate(self, attrs):
        return _validate_band_quant_point(attrs, self.instance)

    def update(self, instance, validated_data):
        qp_data = validated_data.pop("quant_point", None)
        with transaction.atomic():
            band = super().update(instance, validated_data)
            apply_band_type(band, qp_data)
        return band


class BandWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating bands.

    Validation + nested quant_point update logic is shared with BandSerializer
    via _validate_band_quant_point / apply_band_type — a single source of truth
    for the CALIBRATION rules, shared with the editor's band endpoints too.
    """

    quant_point = QuantPointSerializer(required=False, allow_null=True)

    class Meta:
        model = Band
        fields = [
            "band_type",
            "position_y",
            "polygon",
            "bbox_x",
            "bbox_y",
            "bbox_width",
            "bbox_height",
            "estimated_mw_kda",
            "intensity_raw",
            "intensity_peak",
            "intensity_normalized",
            "area_pixels",
            "label",
            "notes",
            "quant_point",
        ]

    def validate(self, attrs):
        return _validate_band_quant_point(attrs, self.instance)

    def update(self, instance, validated_data):
        qp_data = validated_data.pop("quant_point", None)
        with transaction.atomic():
            band = super().update(instance, validated_data)
            apply_band_type(band, qp_data)
        return band


# =============================================================================
# Lane Serializers
# =============================================================================


class LaneSerializer(serializers.ModelSerializer):
    """Serializer for Lane — includes nested bands."""

    bands = BandSerializer(many=True, read_only=True)
    ladder_template_name = serializers.SerializerMethodField()

    class Meta:
        model = Lane
        fields = [
            "id",
            "lane_number",
            "lane_type",
            "detection_source",
            "confidence",
            "lane_shape",
            "x",
            "y",
            "width",
            "height",
            "polygon",
            "is_reduced",
            "protein_load_ug",
            "loading_volume_ul",
            "protein_load_type",
            "loading_volume_ul",
            "sample_name",
            "ladder_template",
            "ladder_template_name",
            "notes",
            "bands",
        ]
        # confidence is YOLO-output; loading_volume_ul is editable via the
        # write serializer (critical for µg/mL → µg conversion in quantification)
        read_only_fields = ["confidence"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_ladder_template_name(self, obj):
        return obj.ladder_template.name if obj.ladder_template else None


class LaneWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating lanes."""

    def validate(self, attrs):
        """Spec 2026-10-10 §4, Rule 1: the box follows the polygon, as the editor's own lane writes."""
        keys = ("lane_shape", "polygon", "x", "y", "width", "height")
        lane = self.instance
        stored = {key: getattr(lane, key) for key in keys} if lane is not None else None
        size = (lane.analysis.gel_image.width, lane.analysis.gel_image.height) if lane is not None else None
        try:
            geometry = normalize_lane_write({k: attrs[k] for k in keys if k in attrs}, stored, size)
        except GeometryRefused as exc:
            raise serializers.ValidationError({"polygon": str(exc)}) from exc
        return {**{k: v for k, v in attrs.items() if k not in keys}, **geometry}

    class Meta:
        model = Lane
        fields = [
            "lane_type",
            "x",
            "y",
            "width",
            "height",
            "polygon",
            "lane_shape",
            "is_reduced",
            "protein_load_ug",
            "loading_volume_ul",
            "protein_load_type",
            "loading_volume_ul",
            "sample_name",
            "ladder_template",
            "notes",
        ]


# =============================================================================
# GelAnalysis Serializers
# =============================================================================


class GelAnalysisListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for analysis list views."""

    gel_image_name = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = GelAnalysis
        fields = [
            "id",
            "name",
            "status",
            "gel_image",
            "gel_image_name",
            "thumbnail_url",
            "total_lanes",
            "total_bands",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_gel_image_name(self, obj):
        return obj.gel_image.original_filename if obj.gel_image else None

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, obj):
        if obj.gel_image and obj.gel_image.thumbnail:
            return obj.gel_image.thumbnail.url
        return None


class GelAnalysisDetailSerializer(serializers.ModelSerializer):
    """Full analysis tree — image + lanes + bands + calibration."""

    gel_image = GelImageDetailSerializer(read_only=True)
    lanes = serializers.SerializerMethodField()
    calibration = serializers.SerializerMethodField()

    class Meta:
        model = GelAnalysis
        fields = [
            "id",
            "name",
            "status",
            "gel_image",
            "total_lanes",
            "total_bands",
            "ladder_lane_number",
            "ladder_type",
            "calibration_coefficients",
            "calibration_r_squared",
            "yolo_gel_type_inference",
            "notes",
            "lanes",
            "calibration",
            "created_by",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]
        # Approval workflow + audit fields are server-managed (driven by the
        # status-transition action, not by ad-hoc PATCH).
        read_only_fields = [
            "calibration_r_squared",
            "yolo_gel_type_inference",
            "created_by",
            "approved_by",
            "approved_at",
            "rejection_reason",
        ]

    @extend_schema_field({"type": "array", "items": {"type": "object"}})
    def get_lanes(self, obj):
        lanes = (
            Lane.objects.filter(analysis=obj)
            .select_related("ladder_template")
            .prefetch_related("bands")
            .order_by("lane_number")
        )
        return LaneSerializer(lanes, many=True).data

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_calibration(self, obj):
        cal = obj.ladder_calibrations.first()
        if not cal:
            return None
        return {
            "id": str(cal.id),
            "method": cal.method,
            "coefficients": cal.coefficients,
            "r_squared": cal.r_squared,
            "matched_band_count": cal.matched_band_count,
            "band_matches": cal.band_matches,
        }


class GelAnalysisWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating analyses."""

    class Meta:
        model = GelAnalysis
        fields = ["gel_image", "name", "ladder_type"]


# =============================================================================
# DensitometryJob Serializer
# =============================================================================


class DensitometryJobSerializer(serializers.ModelSerializer):
    """Serializer for DensitometryJob status polling."""

    class Meta:
        model = DensitometryJob
        fields = [
            "id",
            "analysis",
            "task_id",
            "status",
            "progress",
            "params",
            "lane_ids",
            "result",
            "error_message",
            "created_at",
            "started_at",
            "completed_at",
        ]


# =============================================================================
# LadderTemplate Serializers
# =============================================================================


class LadderBandDefinitionSerializer(serializers.ModelSerializer):
    """Serializer for individual ladder band definitions."""

    class Meta:
        model = LadderBandDefinition
        fields = [
            "id",
            "mw_kda",
            "band_order",
            "relative_intensity",
            "is_reference_band",
            "color",
            # Pattern-matching priors learned from training calibrations
            "expected_rf",
            "expected_rf_tolerance",
            "intensity_rank",
        ]
        # Pattern-matching priors are populated by training pipelines, not by
        # client edits.
        read_only_fields = ["expected_rf", "expected_rf_tolerance", "intensity_rank"]


class LadderTemplateListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for LadderTemplate list views."""

    class Meta:
        model = LadderTemplate
        fields = [
            "id",
            "name",
            "code",
            "manufacturer",
            "category",
            "band_count",
            "mw_range_min",
            "mw_range_max",
            "is_active",
            "is_global",
        ]


class LadderTemplateDetailSerializer(serializers.ModelSerializer):
    """Full serializer with nested band definitions."""

    bands = LadderBandDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model = LadderTemplate
        fields = [
            "id",
            "name",
            "code",
            "manufacturer",
            "catalog_number",
            "category",
            "description",
            "band_count",
            "mw_range_min",
            "mw_range_max",
            "is_active",
            "is_global",
            "bands",
            # Audit fields
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]


# =============================================================================
# SavedComparison Serializer
# =============================================================================


class SavedComparisonSerializer(serializers.ModelSerializer):
    """Serializer for SavedComparison — includes lane count."""

    lane_count = serializers.SerializerMethodField()

    class Meta:
        model = SavedComparison
        fields = [
            "id",
            "name",
            "description",
            "is_public",
            "view_settings",
            "lane_count",
            "created_by",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_lane_count(self, obj):
        return obj.lanes.count()


# =============================================================================
# Densitometry Result Serializer (formalized — see Task A6)
# =============================================================================


class DensitometryResultSerializer(serializers.ModelSerializer):
    """Full Gaussian-fit densitometry result for a single Band.

    Wired by both BandViewSet.densitometry and LaneViewSet.densitometry so the
    payload shape is stable across the two action endpoints.
    """

    class Meta:
        model = DensitometryResult
        fields = [
            "id",
            "band",
            "peak_center_y",
            "peak_amplitude",
            "peak_sigma",
            "fwhm",
            "integrated_area",
            "background_area",
            "corrected_area",
            "fit_r_squared",
            "snr",
            "relative_percent_lane",
            "relative_percent_gel",
            "estimated_amount",
            "estimated_amount_unit",
            "estimated_amount_range",
            "computed_at",
        ]
        read_only_fields = fields


# =============================================================================
# MWMarker Serializer (read-only — see Task A7)
# =============================================================================


class MWMarkerSerializer(serializers.ModelSerializer):
    """Read-only serializer for MWMarker — exposed via the nested
    ``/analyses/<id>/mw-markers/`` action on GelAnalysisViewSet."""

    class Meta:
        model = MWMarker
        fields = [
            "id",
            "lane",
            "band",
            "mw_kda",
            "position_y",
        ]
        read_only_fields = fields


# =============================================================================
# Protein Quantification Serializers (formalized — see Task A8)
# =============================================================================


class ProteinQuantCalibrationPointSerializer(serializers.ModelSerializer):
    """Calibration / control point anchored on a CALIBRATION-typed Band."""

    class Meta:
        model = ProteinQuantCalibrationPoint
        fields = [
            "id",
            "band",
            "load_amount",
            "load_unit",
            "is_excluded_from_fit",
            "role",
            "created_at",
        ]
        read_only_fields = ["id", "role", "created_at"]


class ProteinQuantCalibrationSerializer(serializers.ModelSerializer):
    """A persisted protein quantification calibration (active or superseded)."""

    class Meta:
        model = ProteinQuantCalibration
        fields = [
            "id",
            "analysis",
            "method",
            "unit",
            "coefficients",
            "r_squared",
            "equation",
            "excluded_band_ids",
            "is_active",
            "superseded_at",
            "last_recomputed_at",
            "created_by",
            "created_at",
            "notes",
        ]
        read_only_fields = [
            "id",
            "is_active",
            "superseded_at",
            "last_recomputed_at",
            "created_at",
            "created_by",
        ]


class ProteinQuantFitPreviewSerializer(serializers.Serializer):
    """Input schema for the preview / save endpoints.

    Used purely for OpenAPI schema generation — runtime validation lives in
    QuantParams. ``excluded_band_ids`` is optional.
    """

    method = serializers.ChoiceField(
        choices=[
            ProteinQuantCalibration.METHOD_LINEAR,
            ProteinQuantCalibration.METHOD_POLY2,
            ProteinQuantCalibration.METHOD_4PL,
        ]
    )
    unit = serializers.ChoiceField(
        choices=[
            ProteinQuantCalibration.UNIT_UG,
            ProteinQuantCalibration.UNIT_UG_ML,
        ]
    )
    excluded_band_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class ProteinQuantFitResultSerializer(serializers.Serializer):
    """Output schema for the preview endpoint — wraps the dict produced by
    QuantFitResult.to_dict() so OpenAPI can describe it as an object.

    This serializer is *not* used to serialize at runtime (the function-based
    view still calls ``result.to_dict()`` directly — the result object is a
    dataclass, not a model). It exists purely as a schema reference for
    ``@extend_schema(responses=...)``.
    """

    success = serializers.BooleanField()
    method = serializers.CharField(required=False)
    unit = serializers.CharField(required=False)
    coefficients = serializers.JSONField(required=False)
    r_squared = serializers.FloatField(required=False)
    equation = serializers.CharField(required=False)
    error_message = serializers.CharField(required=False)
    calibration_points = serializers.ListField(required=False)
    control_points = serializers.ListField(required=False)
    sample_projections = serializers.ListField(required=False)
    calibration_area_range = serializers.ListField(
        child=serializers.FloatField(),
        required=False,
        allow_null=True,
        help_text="[min, max] corrected area of the fit's non-excluded standards; each projected point's "
        "calibration_range (IN_RANGE / ABOVE_RANGE / BELOW_RANGE) is read against it.",
    )
