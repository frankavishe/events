from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.orders.models import MoneyField, Order


class Payment(BaseModel):
    """One attempt to pay an order. Bank account numbers and OTPs are never stored."""

    class Method(models.TextChoices):
        ONLINE = "online", _("Online")
        CASH = "cash", _("Cash")

    class Provider(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        TIGO = "tigo", "Tigo Pesa / Mixx"
        AIRTEL = "airtel", "Airtel Money"
        HALOPESA = "halopesa", "HaloPesa"
        AZAMPESA = "azampesa", "AzamPesa"
        BANK = "bank", _("Bank")
        CASH = "cash", _("Cash")

    class Bank(models.TextChoices):
        CRDB = "CRDB", "CRDB"
        NMB = "NMB", "NMB"

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    class ReviewReason(models.TextChoices):
        AMOUNT_MISMATCH = "amount_mismatch", _("Reported amount differs from the order total")
        NOT_PAYABLE = "order_not_payable", _("Money received but the order was not payable")
        DUPLICATE_REFERENCE = "duplicate_reference", _("Gateway reference already used")
        NO_CALLBACK = "no_callback", _("No result from the gateway")

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=6, choices=Method.choices)
    provider = models.CharField(max_length=10, choices=Provider.choices)
    bank_name = models.CharField(max_length=10, choices=Bank.choices, blank=True)
    payer_phone = models.CharField(max_length=16, blank=True, help_text="E.164")
    amount = MoneyField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # NULL (not "") for "none yet", so the unique constraint allows many.
    gateway_reference = models.CharField(max_length=128, unique=True, null=True, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    needs_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=20, choices=ReviewReason.choices, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="success"),
                name="payments_one_success_per_order",
            ),
            models.UniqueConstraint(
                fields=["order", "method"],
                condition=models.Q(status="pending"),
                name="payments_one_pending_per_method",
            ),
            models.CheckConstraint(
                name="payments_amount_positive", condition=models.Q(amount__gt=Decimal("0"))
            ),
        ]

    def __str__(self):
        return f"{self.order} {self.method} {self.status}"
