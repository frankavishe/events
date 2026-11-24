from django.contrib import admin, messages

from apps.common.exceptions import Conflict

from . import services
from .models import ServiceArea, VendorProfile


@admin.register(ServiceArea)
class ServiceAreaAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "contact_phone", "status", "offers_food", "offers_drinks")
    list_filter = ("status", "offers_food", "offers_drinks", "service_areas")
    search_fields = ("business_name", "contact_phone", "user__phone", "user__full_name")
    autocomplete_fields = ("user",)
    filter_horizontal = ("service_areas",)
    # Status only changes through the service-backed actions below.
    readonly_fields = ("id", "status", "approved_by", "approved_at", "created_at", "updated_at")
    actions = ("approve_vendors", "reject_vendors", "suspend_vendors")

    def _run(self, request, queryset, moderate):
        done = 0
        for vendor in queryset:
            try:
                moderate(vendor.pk)
                done += 1
            except Conflict as exc:
                self.message_user(request, f"{vendor}: {exc.detail}", messages.WARNING)
        if done:
            self.message_user(request, f"{done} vendor(s) updated.", messages.SUCCESS)

    @admin.action(description="Approve selected vendors", permissions=["change"])
    def approve_vendors(self, request, queryset):
        self._run(request, queryset, lambda pk: services.approve(pk, request.user))

    @admin.action(description="Reject selected vendors", permissions=["change"])
    def reject_vendors(self, request, queryset):
        self._run(request, queryset, services.reject)

    @admin.action(description="Suspend selected vendors", permissions=["change"])
    def suspend_vendors(self, request, queryset):
        self._run(request, queryset, services.suspend)
