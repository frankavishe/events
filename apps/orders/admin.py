from django.contrib import admin

from .models import Order, OrderLine, OrderStatusChange


class _ReadOnly:
    """Orders change only through services, so every change is validated and audited."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderLineInline(_ReadOnly, admin.TabularInline):
    model = OrderLine
    fields = ("name_snapshot", "unit_snapshot", "unit_price_snapshot", "quantity", "line_total")


class OrderStatusChangeInline(_ReadOnly, admin.TabularInline):
    model = OrderStatusChange
    fields = ("created_at", "from_status", "to_status", "actor", "note")
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(_ReadOnly, admin.ModelAdmin):
    list_display = ("reference", "status", "client", "vendor", "total", "created_at")
    list_filter = ("status", "channel", "contains_alcohol")
    list_select_related = ("client", "vendor")
    search_fields = ("reference", "client__phone", "client__full_name", "vendor__business_name")
    date_hierarchy = "created_at"
    inlines = [OrderLineInline, OrderStatusChangeInline]
