from rest_framework import serializers

from apps.accounts.models import User
from apps.events.models import Event
from apps.payments.serializers import PaymentSerializer
from apps.vendors.serializers import VendorSummarySerializer

from .models import Order, OrderLine, OrderStatusChange

MAX_QUANTITY = 1_000_000


class OrderLineInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(required=False)
    package_id = serializers.UUIDField(required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)


class OrderCreateSerializer(serializers.Serializer):
    """Prices and totals are never accepted from the client."""

    event_id = serializers.UUIDField()
    vendor_id = serializers.UUIDField()
    lines = OrderLineInputSerializer(many=True, allow_empty=False, max_length=100)
    age_confirmed = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ("id", "title", "event_type", "starts_at", "venue", "guest_count")


class OrderClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "full_name", "phone")


class OrderLineSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="name_snapshot")
    unit = serializers.CharField(source="unit_snapshot")
    unit_price = serializers.DecimalField(
        source="unit_price_snapshot", max_digits=12, decimal_places=2
    )

    class Meta:
        model = OrderLine
        fields = (
            "id",
            "item",
            "package",
            "name",
            "unit",
            "unit_price",
            "quantity",
            "line_total",
        )


class OrderStatusChangeSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(
        source="actor.full_name", default=None, allow_null=True, help_text="null = system"
    )

    class Meta:
        model = OrderStatusChange
        fields = ("from_status", "to_status", "actor_name", "note", "created_at")


class OrderListSerializer(serializers.ModelSerializer):
    event = OrderEventSerializer()
    client = OrderClientSerializer()
    vendor = VendorSummarySerializer()

    class Meta:
        model = Order
        fields = (
            "id",
            "reference",
            "status",
            "event",
            "client",
            "vendor",
            "subtotal",
            "total",
            "contains_alcohol",
            "age_confirmed",
            "channel",
            "notes",
            "expires_at",
            "created_at",
        )
        read_only_fields = fields


class OrderSerializer(OrderListSerializer):
    lines = OrderLineSerializer(many=True)
    payments = PaymentSerializer(many=True)
    status_history = OrderStatusChangeSerializer(source="status_changes", many=True)

    class Meta(OrderListSerializer.Meta):
        fields = (*OrderListSerializer.Meta.fields, "lines", "payments", "status_history")
        read_only_fields = fields
