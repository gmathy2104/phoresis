"""
DRF Serializers for Gel Analyzer API.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from gel_analyzer.models import (
    Band,
    DensitometryJob,
    GelAnalysis,
    GelImage,
    LadderBandDefinition,
    LadderTemplate,
    Lane,
    ProteinQuantCalibration,
    ProteinQuantCalibrationPoint,
    SavedComparison,
)

# =============================================================================
# GelImage Serializers
# =============================================================================


class GelImageListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for GelImage list views."""

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
            "gel_type",
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


class GelImageUploadSerializer(serializers.ModelSerializer):
    """Serializer for GelImage upload (multipart)."""

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
    quant_point = QuantPointSerializer(required=False, allow_null=True)

    class Meta:
        model = Band
        fields = [
            "id",
            "lane",
            "band_type",
            "detection_source",
            "position_y",
            "polygon",
            "bbox",
            "estimated_mw_kda",
            "intensity_raw",
            "intensity_peak",
            "intensity_normalized",
            "area_pixels",
            "label",
            "notes",
            "created_at",
            "corrected_area",
            "estimated_amount",
            "estimated_amount_unit",
            "quant_point",
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
        band_type = attrs.get("band_type", getattr(self.instance, "band_type", None))
        qp = attrs.get("quant_point")
        # CALIBRATION requires a quant_point on creation (or when one isn't already
        # attached to the existing instance).
        if band_type == Band.BandType.CALIBRATION and qp is None:
            existing_qp = None
            if self.instance is not None:
                existing_qp = ProteinQuantCalibrationPoint.objects.filter(band=self.instance).first()
            if existing_qp is None:
                raise serializers.ValidationError(
                    "band_type=CALIBRATION requires a quant_point with load_amount and load_unit"
                )
        # Parent lane must be CALIBRATION or CONTROL when band is CALIBRATION
        if band_type == Band.BandType.CALIBRATION:
            lane = attrs.get("lane") or (self.instance.lane if self.instance else None)
            if lane and lane.lane_type not in (Lane.LaneType.CALIBRATION, Lane.LaneType.CONTROL):
                raise serializers.ValidationError(
                    "band_type=CALIBRATION must live in a CALIBRATION or CONTROL lane"
                )
        # Unit consistency with the active calibration of the analysis
        if qp is not None and band_type == Band.BandType.CALIBRATION:
            lane = attrs.get("lane") or (self.instance.lane if self.instance else None)
            if lane is not None:
                analysis = lane.analysis
                active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
                if active and qp.get("load_unit") and qp["load_unit"] != active.unit:
                    raise serializers.ValidationError(
                        f"Unit {qp['load_unit']} differs from the active calibration's unit {active.unit}"
                    )
        return attrs

    def update(self, instance, validated_data):
        qp_data = validated_data.pop("quant_point", None)
        band = super().update(instance, validated_data)
        if band.band_type == Band.BandType.CALIBRATION and qp_data is not None:
            role = (
                ProteinQuantCalibrationPoint.ROLE_CONTROL
                if band.lane.lane_type == Lane.LaneType.CONTROL
                else ProteinQuantCalibrationPoint.ROLE_CALIBRATION
            )
            ProteinQuantCalibrationPoint.objects.update_or_create(
                band=band,
                defaults={
                    "load_amount": qp_data["load_amount"],
                    "load_unit": qp_data["load_unit"],
                    "is_excluded_from_fit": qp_data.get("is_excluded_from_fit", False),
                    "role": role,
                },
            )
        elif band.band_type != Band.BandType.CALIBRATION:
            # type was demoted; remove any orphan point
            ProteinQuantCalibrationPoint.objects.filter(band=band).delete()
        return band


class BandWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating bands."""

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
        band_type = attrs.get("band_type", getattr(self.instance, "band_type", None))
        qp = attrs.get("quant_point")
        if band_type == Band.BandType.CALIBRATION and qp is None:
            existing_qp = None
            if self.instance is not None:
                existing_qp = ProteinQuantCalibrationPoint.objects.filter(band=self.instance).first()
            if existing_qp is None:
                raise serializers.ValidationError(
                    "band_type=CALIBRATION requires a quant_point with load_amount and load_unit"
                )
        if band_type == Band.BandType.CALIBRATION:
            lane = attrs.get("lane") or (self.instance.lane if self.instance else None)
            if lane and lane.lane_type not in (Lane.LaneType.CALIBRATION, Lane.LaneType.CONTROL):
                raise serializers.ValidationError(
                    "band_type=CALIBRATION must live in a CALIBRATION or CONTROL lane"
                )
        if qp is not None and band_type == Band.BandType.CALIBRATION:
            lane = attrs.get("lane") or (self.instance.lane if self.instance else None)
            if lane is not None:
                analysis = lane.analysis
                active = ProteinQuantCalibration.objects.filter(analysis=analysis, is_active=True).first()
                if active and qp.get("load_unit") and qp["load_unit"] != active.unit:
                    raise serializers.ValidationError(
                        f"Unit {qp['load_unit']} differs from the active calibration's unit {active.unit}"
                    )
        return attrs

    def update(self, instance, validated_data):
        qp_data = validated_data.pop("quant_point", None)
        band = super().update(instance, validated_data)
        if band.band_type == Band.BandType.CALIBRATION and qp_data is not None:
            role = (
                ProteinQuantCalibrationPoint.ROLE_CONTROL
                if band.lane.lane_type == Lane.LaneType.CONTROL
                else ProteinQuantCalibrationPoint.ROLE_CALIBRATION
            )
            ProteinQuantCalibrationPoint.objects.update_or_create(
                band=band,
                defaults={
                    "load_amount": qp_data["load_amount"],
                    "load_unit": qp_data["load_unit"],
                    "is_excluded_from_fit": qp_data.get("is_excluded_from_fit", False),
                    "role": role,
                },
            )
        elif band.band_type != Band.BandType.CALIBRATION:
            ProteinQuantCalibrationPoint.objects.filter(band=band).delete()
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
            "lane_shape",
            "x",
            "y",
            "width",
            "height",
            "polygon",
            "is_reduced",
            "protein_load_ug",
            "protein_load_type",
            "loading_volume_ul",
            "sample_name",
            "ladder_template",
            "ladder_template_name",
            "notes",
            "bands",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_ladder_template_name(self, obj):
        return obj.ladder_template.name if obj.ladder_template else None


class LaneWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating lanes."""

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
            "lanes",
            "calibration",
            "created_at",
            "updated_at",
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
        ]


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
        ]


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
