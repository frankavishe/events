from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.orders.models import Order
from apps.vendors.serializers import PhoneField

from .models import Payment

Provider = Payment.Provider
ONLINE_PROVIDERS = [c for c in Provider.choices if c[0] != Provider.CASH]


class PaymentSerializer(serializers.ModelSerializer):
    """Never add the payer's phone, the raw callback or review fields here."""

    class Meta:
        model = Payment
        fields = (
            "id",
            "order",
            "method",
            "provider",
            "bank_name",
            "amount",
            "status",
            "gateway_reference",
            "completed_at",
            "created_at",
        )
        read_only_fields = fields


class PaySerializer(serializers.Serializer):
    """`provider` and `phone` are required online; the bank fields when provider is `bank`."""

    method = serializers.ChoiceField(choices=Payment.Method.choices)
    provider = serializers.ChoiceField(choices=ONLINE_PROVIDERS, required=False)
    phone = PhoneField(required=False)
    bank_name = serializers.ChoiceField(choices=Payment.Bank.choices, required=False)
    account_number = serializers.CharField(required=False, max_length=50, write_only=True)
    otp = serializers.CharField(required=False, max_length=20, write_only=True)

    def validate(self, attrs):
        required = []
        if attrs["method"] == Payment.Method.ONLINE:
            required += ["provider", "phone"]
            if attrs.get("provider") == Provider.BANK:
                required += ["bank_name", "account_number", "otp"]
        missing = {name: _("This field is required.") for name in required if name not in attrs}
        if missing:
            raise serializers.ValidationError(missing)
        # Drop what does not apply to the chosen method.
        return {name: attrs[name] for name in ["method", *required]}


class PayResponseSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField(source="pk")
    status = serializers.ChoiceField(choices=Payment.Status.choices)
    order_status = serializers.ChoiceField(source="order.status", choices=Order.Status.choices)


class RefundSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500)
