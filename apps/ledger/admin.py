from django import forms
from django.contrib import admin
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.common.exceptions import error_messages

from . import services
from .models import CommissionSetting, Payout, VendorEarning


class _AddOnly:
    """Financial history is never edited or deleted."""

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VendorEarning)
class VendorEarningAdmin(_AddOnly, admin.ModelAdmin):
    list_display = (
        "order",
        "vendor",
        "channel",
        "gross",
        "commission_rate",
        "commission_amount",
        "net",
        "reversed",
        "created_at",
    )
    list_filter = ("channel", "reversed")
    list_select_related = ("order", "vendor")
    search_fields = ("order__reference", "vendor__business_name")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


class PayoutForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        needed = ("vendor", "amount", "method", "reference")
        if all(data.get(name) for name in needed):
            try:
                # The admin's add view is one transaction, so the lock holds until saved.
                services.check_payout(**{name: data[name] for name in needed})
            except APIException as exc:
                raise forms.ValidationError(error_messages(exc.detail)) from exc
        return data


@admin.register(Payout)
class PayoutAdmin(_AddOnly, admin.ModelAdmin):
    form = PayoutForm
    fields = ("vendor", "amount", "method", "reference", "note")
    list_display = ("vendor", "amount", "method", "reference", "paid_at", "recorded_by")
    list_filter = ("method",)
    list_select_related = ("vendor", "recorded_by")
    search_fields = ("vendor__business_name", "reference")
    autocomplete_fields = ("vendor",)
    date_hierarchy = "paid_at"

    def save_model(self, request, obj, form, change):
        obj.recorded_by = request.user
        obj.paid_at = timezone.now()
        super().save_model(request, obj, form, change)
        services.log_payout(obj)


@admin.register(CommissionSetting)
class CommissionSettingAdmin(_AddOnly, admin.ModelAdmin):
    """Adding a rate applies it to payments that succeed from now on."""

    fields = ("rate",)
    list_display = ("rate", "effective_from", "set_by")
    list_select_related = ("set_by",)

    def save_model(self, request, obj, form, change):
        obj.set_by = request.user
        super().save_model(request, obj, form, change)
