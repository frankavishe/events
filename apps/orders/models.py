from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.common.money import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS


class MoneyField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class Order(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")
        AWAITING_CASH = "awaiting_cash", _("Awaiting cash payment")
        PAID = "paid", _("Paid")
        FULFILLED = "fulfilled", _("Fulfilled")
        COMPLETED = "completed", _("Completed")
        REFUNDED = "refunded", _("Refunded")

    class Channel(models.TextChoices):
        API = "api", _("API")
        WHATSAPP = "whatsapp", _("WhatsApp")

    reference = models.CharField(max_length=20, unique=True)
    # NULL only once the event of a cancelled, declined or expired order has been deleted.
    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, related_name="orders"
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    vendor = models.ForeignKey(
        "vendors.VendorProfile", on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    subtotal = MoneyField()
    total = MoneyField()
    contains_alcohol = models.BooleanField(default=False)
    age_confirmed = models.BooleanField(default=False)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.API)
    expires_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=["vendor", "status"]),
            models.Index(fields=["client", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="orders_order_totals_positive",
                condition=models.Q(subtotal__gt=Decimal("0"), total__gt=Decimal("0")),
            ),
            models.CheckConstraint(
                name="orders_order_alcohol_needs_age",
                condition=models.Q(contains_alcohol=False) | models.Q(age_confirmed=True),
            ),
        ]

    def __str__(self):
        return self.reference


class OrderLine(BaseModel):
    """A priced snapshot. `item`/`package` may become NULL if the vendor deletes the record."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(
        "catalog.Item", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    package = models.ForeignKey(
        "catalog.Package", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    name_snapshot = models.CharField(max_length=150)
    unit_snapshot = models.CharField(max_length=10)
    unit_price_snapshot = MoneyField()
    quantity = models.PositiveIntegerField()
    line_total = MoneyField()

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                name="orders_line_not_item_and_package",
                condition=models.Q(item__isnull=True) | models.Q(package__isnull=True),
            ),
            models.CheckConstraint(
                name="orders_line_quantity_positive", condition=models.Q(quantity__gte=1)
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.name_snapshot}"


class OrderStatusChange(BaseModel):
    """Append-only audit log. `actor` NULL means the system."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=15, choices=Order.Status.choices, blank=True)
    to_status = models.CharField(max_length=15, choices=Order.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        return f"{self.from_status or '-'} -> {self.to_status}"
