"""Vendor ledger: commission, earnings, payouts and balances."""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import Conflict
from apps.common.logs import log_event
from apps.common.money import format_tzs, to_money
from apps.vendors.models import VendorProfile

from .models import CommissionSetting, Payout, VendorEarning

logger = logging.getLogger(__name__)

Channel = VendorEarning.Channel


# --- Commission ------------------------------------------------------------


def current_rate() -> Decimal:
    """Commission rate in effect now. A migration seeds the first one."""
    return CommissionSetting.objects.filter(effective_from__lte=timezone.now())[:1].get().rate


def set_rate(rate: Decimal, actor) -> CommissionSetting:
    """Use `rate` for payments that succeed from now on."""
    return CommissionSetting.objects.create(rate=rate, set_by=actor)


# --- Earnings --------------------------------------------------------------


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


def vendor_summary(vendor) -> dict[str, Decimal]:
    """Totals over all earnings that were not reversed, and over all payouts."""
    earnings = vendor.earnings.filter(reversed=False)
    net_online = _sum(earnings.filter(channel=Channel.ONLINE), "net")
    owed_cash = _sum(earnings.filter(channel=Channel.CASH), "commission_amount")
    payouts = _sum(vendor.payouts.all(), "amount")
    return {
        "gross": _sum(earnings, "gross"),
        "commission": _sum(earnings, "commission_amount"),
        "net_online": net_online,
        "commission_owed_cash": owed_cash,
        "payouts": payouts,
        "balance": net_online - owed_cash - payouts,
    }


def vendor_balance(vendor) -> Decimal:
    """What the platform owes the vendor; negative when the vendor owes cash commission."""
    return vendor_summary(vendor)["balance"]


def _sum(queryset, field) -> Decimal:
    return queryset.aggregate(total=Sum(field))["total"] or Decimal("0.00")


# --- Payouts ---------------------------------------------------------------


@transaction.atomic
def record_payout(*, vendor, amount: Decimal, method, reference, actor, note="") -> Payout:
    """Record a transfer already made to the vendor outside the system."""
    check_payout(vendor, amount=amount, method=method, reference=reference)
    payout = Payout.objects.create(
        vendor=vendor,
        amount=amount,
        method=method,
        reference=reference,
        paid_at=timezone.now(),
        recorded_by=actor,
        note=note,
    )
    log_payout(payout)
    return payout


def check_payout(vendor, *, amount, method, reference) -> None:
    """Reject a payout that repeats another one or exceeds the balance.

    Must run in the transaction that creates the payout: it locks the vendor, so that
    concurrent payouts wait for each other.
    """
    # no_key: earnings, which reference the vendor, can still be inserted meanwhile.
    VendorProfile.objects.select_for_update(no_key=True).get(pk=vendor.pk)
    if Payout.objects.filter(vendor=vendor, method=method, reference=reference).exists():
        raise Conflict(
            _("A payout with this reference is already recorded for this vendor."),
            code="duplicate_payout",
        )
    balance = vendor_balance(vendor)
    if amount > balance:
        raise ValidationError(
            {
                "amount": _("The amount is more than the vendor's balance of %(balance)s.")
                % {"balance": format_tzs(balance)}
            }
        )


def log_payout(payout) -> None:
    log_event(logger, "payout.recorded", payout=payout.pk, vendor=payout.vendor_id)
