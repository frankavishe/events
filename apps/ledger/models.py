from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.orders.models import MoneyField
from apps.vendors.models import VendorProfile


class CommissionSetting(BaseModel):
    """Rate history. The current rate is the latest row already in effect."""

    rate = models.DecimalField(max_digits=5, decimal_places=4, help_text="0.1000 = 10%")
    effective_from = models.DateTimeField(default=timezone.now)
    # NULL for the seeded default.
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ("-effective_from", "-created_at")
        constraints = [
            models.CheckConstraint(
                name="ledger_commission_rate_range",
                condition=models.Q(rate__gte=Decimal("0"), rate__lte=Decimal("1")),
            )
        ]

    def __str__(self):
        return f"{self.rate} from {self.effective_from:%Y-%m-%d}"


class VendorEarning(BaseModel):
    class Channel(models.TextChoices):
        ONLINE = "online", _("Online")
        CASH = "cash", _("Cash")

    vendor = models.ForeignKey(VendorProfile, on_delete=models.PROTECT, related_name="earnings")
    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="earning")
    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="earning"
    )
    channel = models.CharField(max_length=6, choices=Channel.choices)
    gross = MoneyField()
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4)
    commission_amount = MoneyField()
    net = MoneyField()
    reversed = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                name="ledger_earning_net_adds_up",
                condition=models.Q(gross=models.F("commission_amount") + models.F("net")),
            )
        ]

    def __str__(self):
        return f"{self.order} {self.net}"


class Payout(BaseModel):
    vendor = models.ForeignKey(VendorProfile, on_delete=models.PROTECT, related_name="payouts")
    amount = MoneyField()
    method = models.CharField(max_length=12, choices=VendorProfile.PayoutMethod.choices)
    reference = models.CharField(max_length=100, help_text="External transfer id")
    paid_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("-paid_at",)
        constraints = [
            models.CheckConstraint(
                name="ledger_payout_amount_positive", condition=models.Q(amount__gt=Decimal("0"))
            )
        ]

    def __str__(self):
        return f"{self.vendor} {self.amount}"
