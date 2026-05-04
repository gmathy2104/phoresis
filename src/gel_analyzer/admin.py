"""
Admin configuration for GelAnalyzer models.
"""

import tempfile
from pathlib import Path

from simple_history.admin import SimpleHistoryAdmin

from django.contrib import admin
from django.core.files.base import ContentFile
from django.utils.html import format_html

from gel_analyzer.models import (
    Band,
    GelAnalysis,
    GelImage,
    LadderBandDefinition,
    LadderCalibration,
    LadderTemplate,
    Lane,
    MWMarker,
    SavedComparison,
    SavedComparisonLane,
)
from gel_analyzer.services import GelFileHandler


class LaneInline(admin.TabularInline):
    """Inline for lanes within an analysis."""

    model = Lane
    extra = 0
    fields = ["lane_number", "lane_type", "detection_source", "sample_name", "x", "y", "width", "height"]
    readonly_fields = ["detection_source"]
    show_change_link = True


class GelAnalysisInline(admin.TabularInline):
    """Inline for analyses on a gel image."""

    model = GelAnalysis
    extra = 0
    fields = ["name", "status", "total_lanes", "total_bands", "created_by", "created_at"]
    readonly_fields = ["total_lanes", "total_bands", "created_by", "created_at"]
    show_change_link = True


class BandInline(admin.TabularInline):
    """Inline for bands within a lane."""

    model = Band
    extra = 0
    fields = ["position_y", "detection_source", "estimated_mw_kda", "intensity_normalized", "confidence"]
    readonly_fields = ["detection_source", "confidence"]
    show_change_link = True


@admin.register(GelImage)
class GelImageAdmin(SimpleHistoryAdmin):
    """Admin for GelImage model."""

    list_display = [
        "thumbnail_preview",
        "original_filename",
        "gel_type_badge",
        "file_format",
        "dimensions",
        "uploaded_by",
        "uploaded_at",
        "analysis_count",
    ]
    list_filter = ["gel_type", "file_format", "uploaded_at"]
    search_fields = ["original_filename", "description"]
    ordering = ["-uploaded_at"]
    readonly_fields = [
        "id",
        "uploaded_at",
        "updated_at",
        "image_preview",
        "file_size_bytes",
        "width",
        "height",
        "bit_depth",
        "scanner_metadata",
    ]
    raw_id_fields = ["uploaded_by"]
    date_hierarchy = "uploaded_at"

    fieldsets = (
        (None, {"fields": ("id", "original_filename", "gel_type", "description")}),
        ("Files", {"fields": ("original_file", "display_file", "thumbnail", "image_preview")}),
        (
            "Metadata",
            {
                "fields": ("file_format", "file_size_bytes", "width", "height", "bit_depth", "scanner_metadata"),
            },
        ),
        (
            "Audit",
            {
                "fields": ("uploaded_by", "uploaded_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [GelAnalysisInline]

    def thumbnail_preview(self, obj):
        """Display thumbnail in list view."""
        if obj.thumbnail:
            return format_html('<img src="{}" height="50" style="border-radius: 4px;" />', obj.thumbnail.url)
        return "-"

    thumbnail_preview.short_description = "Preview"

    def image_preview(self, obj):
        """Display larger image in detail view."""
        if obj.display_file:
            return format_html('<img src="{}" style="max-height: 400px; border-radius: 4px;" />', obj.display_file.url)
        elif obj.thumbnail:
            return format_html('<img src="{}" style="max-height: 200px; border-radius: 4px;" />', obj.thumbnail.url)
        return "No preview available"

    image_preview.short_description = "Image Preview"

    def gel_type_badge(self, obj):
        """Display gel type as a colored badge."""
        colors = {
            "SDS_PAGE": "#3B71CA",
            "DOT_BLOT": "#14A44D",
            "WESTERN_BLOT": "#E4A11B",
            "UNKNOWN": "#6B7280",
        }
        color = colors.get(obj.gel_type, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_gel_type_display(),
        )

    gel_type_badge.short_description = "Type"
    gel_type_badge.admin_order_field = "gel_type"

    def dimensions(self, obj):
        """Display image dimensions."""
        if obj.width and obj.height:
            return f"{obj.width} x {obj.height}"
        return "-"

    dimensions.short_description = "Size"

    def analysis_count(self, obj):
        """Display number of analyses."""
        count = obj.analyses.count()
        return format_html(
            '<span style="background-color: #54B4D3; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            count,
        )

    analysis_count.short_description = "Analyses"

    def save_model(self, request, obj, form, change):
        """Auto-populate fields on save."""
        # Set uploaded_by if not set
        if not obj.uploaded_by:
            obj.uploaded_by = request.user

        # If original file changed, process it
        if "original_file" in form.changed_data and obj.original_file:
            # Get original filename
            obj.original_filename = obj.original_file.name.split("/")[-1]

            # Process the file to generate display and thumbnail
            try:
                # Save the file temporarily to process it
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(obj.original_filename).suffix) as tmp:
                    for chunk in obj.original_file.chunks():
                        tmp.write(chunk)
                    tmp_path = Path(tmp.name)

                # Process the uploaded file
                result = GelFileHandler.process_uploaded_file(tmp_path)

                # Update metadata
                obj.file_format = result["metadata"]["format"]
                obj.file_size_bytes = result["metadata"]["file_size_bytes"]
                obj.width = result["metadata"]["width"]
                obj.height = result["metadata"]["height"]
                obj.bit_depth = result["metadata"]["bit_depth"]

                # Save display file
                display_filename = f"{Path(obj.original_filename).stem}_display.png"
                obj.display_file.save(display_filename, ContentFile(result["display_bytes"]), save=False)

                # Save thumbnail
                thumbnail_filename = f"{Path(obj.original_filename).stem}_thumb.png"
                obj.thumbnail.save(thumbnail_filename, ContentFile(result["thumbnail_bytes"]), save=False)

                # Clean up temp file
                tmp_path.unlink()

            except Exception as e:
                # Log error but don't prevent save
                from phoresis_core.logging_config import get_logger

                logger = get_logger(__name__)
                logger.error(f"Failed to process gel image: {e}")

        super().save_model(request, obj, form, change)


@admin.register(GelAnalysis)
class GelAnalysisAdmin(SimpleHistoryAdmin):
    """Admin for GelAnalysis model."""

    list_display = [
        "gel_image",
        "name",
        "status_badge",
        "total_lanes",
        "total_bands",
        "created_by",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = ["name", "gel_image__original_filename"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at", "approved_at"]
    autocomplete_fields = ["gel_image"]
    raw_id_fields = ["created_by", "approved_by"]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("id", "gel_image", "name", "status")}),
        (
            "MW Calibration",
            {
                "fields": ("ladder_lane_number", "ladder_type", "calibration_coefficients", "calibration_r_squared"),
                "classes": ("collapse",),
            },
        ),
        (
            "Detection Results",
            {
                "fields": ("yolo_detection_results", "yolo_gel_type_inference"),
                "classes": ("collapse",),
            },
        ),
        (
            "Summary",
            {
                "fields": ("total_lanes", "total_bands", "notes"),
            },
        ),
        (
            "Approval",
            {
                "fields": ("approved_by", "approved_at", "rejection_reason"),
                "classes": ("collapse",),
            },
        ),
        (
            "Audit",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [LaneInline]

    def status_badge(self, obj):
        """Display status as a colored badge."""
        colors = {
            "DRAFT": "#6B7280",
            "IN_PROGRESS": "#E4A11B",
            "COMPLETED": "#14A44D",
            "APPROVED": "#3B71CA",
            "REJECTED": "#DC4C64",
        }
        color = colors.get(obj.status, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"
    status_badge.admin_order_field = "status"

    def save_model(self, request, obj, form, change):
        """Auto-populate created_by on save."""
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Lane)
class LaneAdmin(admin.ModelAdmin):
    """Admin for Lane model."""

    list_display = [
        "analysis",
        "lane_number",
        "lane_type_badge",
        "detection_source",
        "sample_name",
        "band_count",
    ]
    list_filter = ["lane_type", "detection_source"]
    search_fields = ["sample_name", "analysis__gel_image__original_filename"]
    ordering = ["analysis", "lane_number"]
    autocomplete_fields = ["analysis"]

    fieldsets = (
        (None, {"fields": ("analysis", "lane_number", "lane_type")}),
        (
            "Detection",
            {
                "fields": ("detection_source", "confidence"),
            },
        ),
        (
            "Geometry",
            {
                "fields": ("x", "y", "width", "height"),
            },
        ),
        (
            "Sample",
            {
                "fields": ("sample_name", "sample_metadata"),
            },
        ),
        (
            "Notes",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [BandInline]

    def lane_type_badge(self, obj):
        """Display lane type as a colored badge."""
        colors = {
            "SAMPLE": "#3B71CA",
            "LADDER": "#E4A11B",
            "EMPTY": "#6B7280",
            "CONTROL": "#14A44D",
            "DOT": "#8B5CF6",
        }
        color = colors.get(obj.lane_type, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_lane_type_display(),
        )

    lane_type_badge.short_description = "Type"

    def band_count(self, obj):
        """Display number of bands in lane."""
        return obj.bands.count()

    band_count.short_description = "Bands"


@admin.register(Band)
class BandAdmin(admin.ModelAdmin):
    """Admin for Band model."""

    list_display = [
        "id_short",
        "lane",
        "position_y",
        "detection_source_badge",
        "estimated_mw_kda",
        "intensity_normalized",
        "confidence",
    ]
    list_filter = ["detection_source", "lane__lane_type"]
    search_fields = ["lane__analysis__gel_image__original_filename", "label", "notes"]
    ordering = ["lane", "position_y"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["lane"]
    raw_id_fields = ["created_by"]

    fieldsets = (
        (None, {"fields": ("id", "lane", "label")}),
        (
            "Detection",
            {
                "fields": ("detection_source", "confidence"),
            },
        ),
        (
            "Position",
            {
                "fields": ("position_y", "polygon"),
            },
        ),
        (
            "Bounding Box",
            {
                "fields": ("bbox_x", "bbox_y", "bbox_width", "bbox_height"),
                "classes": ("collapse",),
            },
        ),
        (
            "MW Estimation",
            {
                "fields": ("estimated_mw_kda", "mw_estimation_method"),
            },
        ),
        (
            "Densitometry",
            {
                "fields": ("intensity_raw", "intensity_normalized", "area_pixels"),
            },
        ),
        (
            "Notes",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
            },
        ),
        (
            "Audit",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8]

    id_short.short_description = "ID"

    def detection_source_badge(self, obj):
        """Display detection source as a colored badge."""
        colors = {
            "MANUAL": "#3B71CA",
            "YOLO": "#14A44D",
            "SAM": "#8B5CF6",
        }
        color = colors.get(obj.detection_source, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_detection_source_display(),
        )

    detection_source_badge.short_description = "Source"


@admin.register(MWMarker)
class MWMarkerAdmin(admin.ModelAdmin):
    """Admin for MWMarker model."""

    list_display = ["lane", "mw_kda", "position_y", "has_band"]
    list_filter = ["lane__analysis"]
    ordering = ["lane", "-mw_kda"]
    autocomplete_fields = ["lane", "band"]

    def has_band(self, obj):
        """Check if marker is linked to a band."""
        return obj.band is not None

    has_band.boolean = True
    has_band.short_description = "Linked"


# =============================================================================
# Ladder Template Models
# =============================================================================


class LadderBandDefinitionInline(admin.TabularInline):
    """Inline for bands within a ladder template."""

    model = LadderBandDefinition
    extra = 1
    fields = ["band_order", "mw_kda", "color", "is_reference_band", "relative_intensity"]
    ordering = ["band_order"]


@admin.register(LadderTemplate)
class LadderTemplateAdmin(SimpleHistoryAdmin):
    """Admin for LadderTemplate model."""

    list_display = [
        "name",
        "manufacturer",
        "category_badge",
        "band_count",
        "mw_range_display",
        "global_badge",
        "is_active",
        "created_at",
    ]
    list_filter = ["category", "manufacturer", "is_global", "is_active"]
    search_fields = ["name", "code", "manufacturer", "catalog_number"]
    ordering = ["manufacturer", "name"]
    readonly_fields = ["id", "created_at", "updated_at", "band_count", "mw_range_min", "mw_range_max"]
    raw_id_fields = ["created_by"]

    fieldsets = (
        (None, {"fields": ("id", "name", "code", "manufacturer", "catalog_number")}),
        (
            "Classification",
            {
                "fields": ("category", "description"),
            },
        ),
        (
            "Computed Fields",
            {
                "fields": ("band_count", "mw_range_min", "mw_range_max"),
                "classes": ("collapse",),
            },
        ),
        (
            "Permissions",
            {
                "fields": ("is_global", "is_active"),
            },
        ),
        (
            "Audit",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [LadderBandDefinitionInline]

    def category_badge(self, obj):
        """Display category as a colored badge."""
        colors = {
            "UNSTAINED": "#6B7280",
            "PRESTAINED": "#3B71CA",
            "DUAL_COLOR": "#8B5CF6",
            "BROAD_RANGE": "#14A44D",
            "LOW_RANGE": "#E4A11B",
            "HIGH_RANGE": "#DC4C64",
        }
        color = colors.get(obj.category, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_category_display(),
        )

    category_badge.short_description = "Category"
    category_badge.admin_order_field = "category"

    def mw_range_display(self, obj):
        """Display MW range as formatted string."""
        if obj.mw_range_min and obj.mw_range_max:
            return f"{obj.mw_range_min:.0f}-{obj.mw_range_max:.0f} kDa"
        return "-"

    mw_range_display.short_description = "MW Range"

    def global_badge(self, obj):
        """Display global status as a badge."""
        if obj.is_global:
            return format_html(
                '<span style="background-color: #14A44D; color: white; padding: 2px 8px; '
                'border-radius: 4px; font-size: 11px;">Global</span>'
            )
        return format_html(
            '<span style="background-color: #6B7280; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">User</span>'
        )

    global_badge.short_description = "Scope"

    def save_model(self, request, obj, form, change):
        """Auto-populate created_by on save."""
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        """Update computed fields after saving bands."""
        super().save_related(request, form, formsets, change)
        # Recalculate computed fields after bands are saved
        form.instance.update_computed_fields()


@admin.register(LadderCalibration)
class LadderCalibrationAdmin(SimpleHistoryAdmin):
    """Admin for LadderCalibration model."""

    list_display = [
        "analysis",
        "ladder_lane",
        "template",
        "method_badge",
        "r_squared_display",
        "matched_band_count",
        "created_at",
    ]
    list_filter = ["method", "created_at"]
    search_fields = ["analysis__name", "template__name"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at"]
    autocomplete_fields = ["analysis", "ladder_lane", "template"]
    raw_id_fields = ["created_by"]

    fieldsets = (
        (None, {"fields": ("id", "analysis", "ladder_lane", "template")}),
        (
            "Calibration Results",
            {
                "fields": ("method", "coefficients", "r_squared", "matched_band_count"),
            },
        ),
        (
            "Band Matches",
            {
                "fields": ("band_matches",),
                "classes": ("collapse",),
            },
        ),
        (
            "Audit",
            {
                "fields": ("created_by", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def method_badge(self, obj):
        """Display method as a colored badge."""
        colors = {
            "LOG_LINEAR": "#3B71CA",
            "POLYNOMIAL_2": "#14A44D",
            "POLYNOMIAL_3": "#8B5CF6",
        }
        color = colors.get(obj.method, "#6B7280")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_method_display(),
        )

    method_badge.short_description = "Method"
    method_badge.admin_order_field = "method"

    def r_squared_display(self, obj):
        """Display R² with color coding based on quality."""
        if obj.r_squared >= 0.99:
            color = "#14A44D"  # Green - excellent
        elif obj.r_squared >= 0.95:
            color = "#54B4D3"  # Teal - good
        elif obj.r_squared >= 0.90:
            color = "#E4A11B"  # Yellow - acceptable
        else:
            color = "#DC4C64"  # Red - poor
        return format_html('<span style="color: {}; font-weight: bold;">{:.4f}</span>', color, obj.r_squared)

    r_squared_display.short_description = "R²"
    r_squared_display.admin_order_field = "r_squared"

    def save_model(self, request, obj, form, change):
        """Auto-populate created_by on save."""
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ──────────────────────────────────────────────────────────────
# Saved Comparison Admin
# ──────────────────────────────────────────────────────────────


class SavedComparisonLaneInline(admin.TabularInline):
    """Inline for lanes within a saved comparison."""

    model = SavedComparisonLane
    extra = 0
    fields = ["lane", "order"]
    ordering = ["order"]


@admin.register(SavedComparison)
class SavedComparisonAdmin(SimpleHistoryAdmin):
    """Admin for saved gel lane comparisons."""

    list_display = ["name", "created_by", "lane_count_display", "is_public", "created_at", "updated_at"]
    list_filter = ["is_public", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["-updated_at"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["created_by"]
    inlines = [SavedComparisonLaneInline]

    def lane_count_display(self, obj):
        return obj.lanes.count()

    lane_count_display.short_description = "Lanes"
