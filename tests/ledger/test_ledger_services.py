from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ledger import services
from apps.ledger.models import CommissionSetting, Payout, VendorEarning
from tests.factories import AdminFactory, PaymentFactory, VendorProfileFactory

pytestmark = pytest.mark.django_db

CASH = {"method": "cash", "provider": "cash"}


def paid(amount="150000.00", vendor=None, **kwargs):
    vendor = vendor or VendorProfileFactory()
    return PaymentFactory(
        order__subtotal=Decimal(amount), order__vendor=vendor, status="success", **kwargs
    )


def set_rate(rate, when=None):
    return CommissionSetting.objects.create(
        rate=Decimal(rate), effective_from=when or timezone.now()
    )


def test_seeded_rate():
    assert services.current_rate() == Decimal("0.1000")


def test_current_rate_ignores_future():
    set_rate("0.2000")
    set_rate("0.3000", timezone.now() + timedelta(days=1))
    assert services.current_rate() == Decimal("0.2000")


@pytest.mark.parametrize("rate", ["-0.0001", "1.0001"])
def test_rate_bounds(rate):
    with pytest.raises(IntegrityError), transaction.atomic():
        set_rate(rate)


@pytest.mark.parametrize(
    ("gross", "commission"),
    [("150000.00", "15000.00"), ("0.05", "0.01"), ("0.04", "0.00"), ("100.25", "10.03")],
)
def test_rounds_half_up(gross, commission):
    earning = services.record_earning(paid(gross))
    assert earning.commission_amount == Decimal(commission)
    assert earning.net == Decimal(gross) - Decimal(commission)


def test_rate_at_payment_time_and_idempotency():
    payment = paid()
    first = services.record_earning(payment)
    set_rate("0.2000")
    assert services.record_earning(payment).pk == first.pk
    first.refresh_from_db()
    assert first.commission_rate == Decimal("0.1000")
    assert services.record_earning(paid()).commission_rate == Decimal("0.2000")


def test_balance_formula():
    vendor = VendorProfileFactory()
    assert services.vendor_balance(vendor) == Decimal("0.00")
    services.record_earning(paid("100000.00", vendor))
    cash = services.record_earning(paid("50000.00", vendor, **CASH))
    services.record_earning(paid())  # another vendor
    assert cash.channel == "cash"
    Payout.objects.create(
        vendor=vendor,
        amount=Decimal("20000"),
        method="bank",
        reference="T1",
        paid_at=timezone.now(),
        recorded_by=AdminFactory(),
    )
    assert services.vendor_balance(vendor) == Decimal("65000.00")


def test_cash_only_balance_is_negative():
    vendor = VendorProfileFactory()
    services.record_earning(paid("50000.00", vendor, **CASH))
    assert services.vendor_balance(vendor) == Decimal("-5000.00")


@pytest.mark.parametrize("extra", [{}, CASH])
def test_reversal(extra):
    payment = paid(**extra)
    services.record_earning(payment)
    services.reverse_earning(payment.order)
    assert VendorEarning.objects.get().reversed
    assert services.vendor_balance(payment.order.vendor) == Decimal("0.00")
