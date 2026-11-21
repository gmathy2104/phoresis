"""Read-only lists: the first way to see how the tours are used (who saw which version, where people leave)."""

from django.contrib import admin

from guided_tours.models import TourEvent, TourProgress


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TourProgress)
class TourProgressAdmin(_ReadOnly):
    list_display = ("user", "tour_id", "version", "status", "updated_at")
    list_filter = ("tour_id", "status")
    search_fields = ("user__username", "tour_id")


@admin.register(TourEvent)
class TourEventAdmin(_ReadOnly):
    list_display = ("created_at", "user", "tour_id", "version", "event", "step_index", "step_key", "detail")
    list_filter = ("tour_id", "event")
    search_fields = ("user__username", "tour_id", "step_key")
    date_hierarchy = "created_at"
