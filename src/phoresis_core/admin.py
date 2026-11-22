"""Admin registrations for phoresis_core."""

from django.contrib import admin

from .models import ArchivedMediaFile, ErrorLog


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "level", "source_type", "app_label", "exception_type", "error_id", "is_acknowledged")
    list_filter = ("level", "source_type", "app_label", "is_acknowledged")
    search_fields = ("message", "exception_type", "error_id", "view_name")
    date_hierarchy = "timestamp"
    readonly_fields = tuple(
        f.name for f in ErrorLog._meta.fields if f.name not in ("is_acknowledged", "acknowledged_by", "acknowledged_at")
    )


@admin.register(ArchivedMediaFile)
class ArchivedMediaFileAdmin(admin.ModelAdmin):
    """Read-only: rows are written by the archive pass, and deleting one would orphan the file."""

    list_display = ("name", "size_bytes", "archived_at", "delete_pending")
    list_filter = ("delete_pending",)
    search_fields = ("name",)
    date_hierarchy = "archived_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
