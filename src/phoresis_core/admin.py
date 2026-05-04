"""Admin registrations for phoresis_core."""

from django.contrib import admin

from .models import ErrorLog


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "level", "source_type", "app_label", "exception_type", "error_id", "is_acknowledged")
    list_filter = ("level", "source_type", "app_label", "is_acknowledged")
    search_fields = ("message", "exception_type", "error_id", "view_name")
    date_hierarchy = "timestamp"
    readonly_fields = tuple(
        f.name for f in ErrorLog._meta.fields if f.name not in ("is_acknowledged", "acknowledged_by", "acknowledged_at")
    )
