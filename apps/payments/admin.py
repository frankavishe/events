from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only except for clearing the review flag."""

    list_display = ("order", "method", "provider", "amount", "status", "needs_review", "created_at")
    list_filter = ("needs_review", "status", "method", "provider", "review_reason")
    list_select_related = ("order",)
    search_fields = ("order__reference", "gateway_reference", "payer_phone")
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Payment._meta.fields if f.name != "needs_review"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # Only this column, so a result arriving meanwhile is not overwritten.
        obj.save(update_fields=["needs_review", "updated_at"])
