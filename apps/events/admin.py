from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "client", "starts_at", "venue", "guest_count")
    list_filter = ("event_type", "service_area")
    list_select_related = ("client",)
    search_fields = ("title", "venue", "client__phone", "client__full_name")
    autocomplete_fields = ("client", "service_area")
    date_hierarchy = "starts_at"
