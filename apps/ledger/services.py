"""Vendor ledger: commission, earnings and balances."""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.common.money import to_money

from .models import CommissionSetting, VendorEarning

Channel = VendorEarning.Channel


def current_rate() -> Decimal:
    """Commission rate in effect now. A migration seeds the first one."""
    return CommissionSetting.objects.filter(effective_from__lte=timezone.now())[:1].get().rate


def record_earning(payment) -> VendorEarning:
    """Record the vendor's earning for a successful payment, once per order."""
    order = payment.order
    rate = current_rate()
    gross = to_money(payment.amount)
    commission = to_money(gross * rate)
    earning, _created = VendorEarning.objects.get_or_create(
        order=order,
        defaults={
            "vendor": order.vendor,
            "payment": payment,
            "channel": payment.method,
            "gross": gross,
            "commission_rate": rate,
            "commission_amount": commission,
            "net": gross - commission,
        },
    )
    return earning


def reverse_earning(order) -> None:
    VendorEarning.objects.filter(order=order).update(reversed=True, updated_at=timezone.now())


def vendor_balance(vendor) -> Decimal:
    """What the platform owes the vendor; negative when the vendor owes cash commission."""
    earnings = vendor.earnings.filter(reversed=False)
    online = _sum(earnings.filter(channel=Channel.ONLINE), "net")
    cash_commission = _sum(earnings.filter(channel=Channel.CASH), "commission_amount")
    return online - cash_commission - _sum(vendor.payouts.all(), "amount")


def _sum(queryset, field) -> Decimal:
    return queryset.aggregate(total=Sum(field))["total"] or Decimal("0.00")
