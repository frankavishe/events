from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ledger import services
from apps.ledger.models import CommissionSetting, Payout
from tests.factories import AdminFactory, PaymentFactory, VendorProfileFactory

pytestmark = pytest.mark.django_db

ADD_PAYOUT = "admin:ledger_payout_add"
ADD_RATE = "admin:ledger_commissionsetting_add"


@pytest.fixture
def site(client):
    client.force_login(AdminFactory(is_superuser=True))
    return client


@pytest.fixture
def earning():
    return services.record_earning(
        PaymentFactory(order__subtotal=Decimal("100000"), status="success")
    )


def form(vendor, amount):
    return {
        "vendor": str(vendor.pk),
        "amount": amount,
        "method": "bank",
        "reference": "T1",
        "note": "",
    }


def test_payout_can_be_added(site, earning):
    response = site.post(reverse(ADD_PAYOUT), form(earning.vendor, "90000"))
    assert response.status_code == 302
    assert Payout.objects.get().recorded_by.role == "admin"
    assert services.vendor_balance(earning.vendor) == 0


def test_over_balance_and_repeats_are_form_errors(site, earning):
    url = reverse(ADD_PAYOUT)
    assert site.post(url, form(earning.vendor, "90001")).status_code == 200
    assert not Payout.objects.exists()
    assert site.post(url, form(earning.vendor, "1")).status_code == 302
    assert site.post(url, form(earning.vendor, "1")).status_code == 200
    assert Payout.objects.count() == 1


@pytest.mark.parametrize("amount", ["", "0", "-1"])
def test_invalid_amount_is_a_form_error(site, earning, amount):
    assert site.post(reverse(ADD_PAYOUT), form(earning.vendor, amount)).status_code == 200
    assert not Payout.objects.exists()


def test_commission_can_be_added(site):
    assert site.post(reverse(ADD_RATE), {"rate": "0.2"}).status_code == 302
    assert services.current_rate() == Decimal("0.2")
    assert CommissionSetting.objects.get(rate=Decimal("0.2")).set_by is not None


@pytest.mark.parametrize("rate", ["-0.1", "1.5"])
def test_invalid_commission_is_a_form_error(site, rate):
    assert site.post(reverse(ADD_RATE), {"rate": rate}).status_code == 200
    assert services.current_rate() == Decimal("0.1")


def test_history_is_read_only(site, earning):
    payout = Payout.objects.create(
        vendor=VendorProfileFactory(),
        amount=1,
        method="bank",
        reference="X",
        paid_at=timezone.now(),
        recorded_by=AdminFactory(),
    )
    assert site.get(reverse("admin:ledger_vendorearning_add")).status_code == 403
    rows = {
        "payout": payout,
        "vendorearning": earning,
        "commissionsetting": CommissionSetting.objects.get(),
    }
    for model, row in rows.items():
        change = reverse(f"admin:ledger_{model}_change", args=[row.pk])
        delete = reverse(f"admin:ledger_{model}_delete", args=[row.pk])
        assert site.get(reverse(f"admin:ledger_{model}_changelist")).status_code == 200
        assert site.get(change).status_code == 200
        assert site.post(change, {}).status_code == 403
        assert site.post(delete, {"post": "yes"}).status_code == 403
