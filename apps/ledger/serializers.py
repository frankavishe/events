from decimal import Decimal

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from apps.common.money import CENT, MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.vendors.models import VendorProfile
from apps.vendors.serializers import VendorSummarySerializer

from .models import CommissionSetting, Payout, VendorEarning


def _total():
    # Wider than one amount: these are sums.
    return serializers.DecimalField(max_digits=20, decimal_places=MONEY_DECIMAL_PLACES)


class LedgerSummarySerializer(serializers.Serializer):
    """Reversed earnings are left out. `balance` = net_online - commission_owed_cash - payouts."""

    gross = _total()
    commission = _total()
    net_online = _total()
    commission_owed_cash = _total()
    payouts = _total()
    balance = _total()


class EarningSerializer(serializers.ModelSerializer):
    order_reference = serializers.CharField(source="order.reference")

    class Meta:
        model = VendorEarning
        fields = (
            "id",
            "order",
            "order_reference",
            "channel",
            "gross",
            "commission_rate",
            "commission_amount",
            "net",
            "reversed",
            "created_at",
        )
        read_only_fields = fields


class CommissionSerializer(serializers.ModelSerializer):
    set_by_name = serializers.CharField(
        source="set_by.full_name", default=None, allow_null=True, help_text="null = system"
    )

    class Meta:
        model = CommissionSetting
        fields = ("id", "rate", "effective_from", "set_by_name")
        read_only_fields = fields


class CommissionInputSerializer(serializers.Serializer):
    rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        help_text="0.1000 = 10%",
    )


class VendorPayoutSerializer(serializers.ModelSerializer):
    """What the vendor sees. Never add the admin's note or name here."""

    class Meta:
        model = Payout
        fields = ("id", "amount", "method", "reference", "paid_at")
        read_only_fields = fields


class AdminPayoutSerializer(serializers.ModelSerializer):
    vendor = VendorSummarySerializer()
    recorded_by_name = serializers.CharField(source="recorded_by.full_name")

    class Meta:
        model = Payout
        fields = (
            "id",
            "vendor",
            "amount",
            "method",
            "reference",
            "paid_at",
            "recorded_by_name",
            "note",
        )
        read_only_fields = fields


class PayoutInputSerializer(serializers.Serializer):
    vendor_id = serializers.PrimaryKeyRelatedField(
        source="vendor", queryset=VendorProfile.objects.all(), pk_field=serializers.UUIDField()
    )
    amount = serializers.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, min_value=CENT
    )
    method = serializers.ChoiceField(choices=VendorProfile.PayoutMethod.choices)
    reference = serializers.CharField(max_length=100)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


# --- Pages, as documented in the OpenAPI schema ----------------------------


class _PageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


@extend_schema_serializer(many=False)
class EarningPageSerializer(_PageSerializer):
    summary = LedgerSummarySerializer()
    results = EarningSerializer(many=True)


@extend_schema_serializer(many=False)
class CommissionPageSerializer(_PageSerializer):
    current_rate = serializers.DecimalField(max_digits=5, decimal_places=4)
    results = CommissionSerializer(many=True)
