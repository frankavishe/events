from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.serializers import RegisterSerializer, UserSerializer
from apps.common.phone import InvalidPhoneNumber, normalize_phone

from . import services
from .models import ServiceArea, VendorProfile


class PhoneField(serializers.CharField):
    """Accepts any supported phone format and returns E.164."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 32)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_phone(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(_("Enter a valid phone number.")) from exc


class ServiceAreaIdsField(serializers.ManyRelatedField):
    def __init__(self, **kwargs):
        kwargs.setdefault(
            "child_relation",
            serializers.PrimaryKeyRelatedField(queryset=ServiceArea.objects.all()),
        )
        kwargs.setdefault("source", "service_areas")
        kwargs.setdefault("write_only", True)
        kwargs.setdefault("allow_empty", False)
        super().__init__(**kwargs)


def _validate_offers(attrs, instance=None):
    food = attrs.get("offers_food", getattr(instance, "offers_food", False))
    drinks = attrs.get("offers_drinks", getattr(instance, "offers_drinks", False))
    if not (food or drinks):
        raise serializers.ValidationError({"offers_food": _("A vendor must offer food or drinks.")})


class ServiceAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceArea
        fields = ("id", "name")


class VendorSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorProfile
        fields = ("id", "business_name")


class PublicVendorSerializer(serializers.ModelSerializer):
    """What anyone may see. Never add payout or approval fields here."""

    service_areas = ServiceAreaSerializer(many=True, read_only=True)

    class Meta:
        model = VendorProfile
        fields = (
            "id",
            "business_name",
            "description",
            "contact_phone",
            "offers_food",
            "offers_drinks",
            "min_notice_days",
            "service_areas",
        )


class VendorProfileSerializer(serializers.ModelSerializer):
    """The vendor's own profile (also returned to admins)."""

    contact_phone = PhoneField()
    service_areas = ServiceAreaSerializer(many=True, read_only=True)
    service_area_ids = ServiceAreaIdsField(required=False)

    class Meta:
        model = VendorProfile
        fields = (
            "id",
            "business_name",
            "description",
            "contact_phone",
            "status",
            "approved_at",
            "offers_food",
            "offers_drinks",
            "min_notice_days",
            "service_areas",
            "service_area_ids",
            "payout_method",
            "payout_account_name",
            "payout_account_number",
            "payout_provider",
            "created_at",
        )
        read_only_fields = ("id", "status", "approved_at", "created_at")

    def validate(self, attrs):
        _validate_offers(attrs, self.instance)
        return attrs


class VendorRegisterSerializer(RegisterSerializer):
    business_name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    contact_phone = PhoneField(required=False)
    offers_food = serializers.BooleanField(default=False)
    offers_drinks = serializers.BooleanField(default=False)
    min_notice_days = serializers.IntegerField(min_value=0, max_value=365, default=2)
    service_area_ids = ServiceAreaIdsField()

    def validate(self, attrs):
        _validate_offers(attrs)
        return super().validate(attrs)

    def create(self, validated_data):
        return services.register_vendor(**validated_data)


class VendorRegisterResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    vendor = VendorProfileSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()
