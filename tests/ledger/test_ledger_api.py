from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.ledger import services
from apps.ledger.models import CommissionSetting, Payout, VendorEarning
from apps.orders.models import Order
from apps.payments.models import Payment
from tests.factories import (
    AdminFactory,
    ClientFactory,
    PaymentFactory,
    VendorProfileFactory,
    VendorUserFactory,
)

EARNINGS = "/api/v1/vendor/earnings/"
PAYOUTS = "/api/v1/vendor/payouts/"
COMMISSION = "/api/v1/admin/commission/"
ADMIN_PAYOUTS = "/api/v1/admin/payouts/"
CASH = {"method": "cash", "provider": "cash"}
NO_ID = "00000000-0000-0000-0000-000000000000"


def earn(vendor, amount="100000.00", **kwargs):
    payment = PaymentFactory(
        order__subtotal=Decimal(amount), order__vendor=vendor, status="success", **kwargs
    )
    return services.record_earning(payment)


def pay_out(vendor, amount="20000", reference="T"):
    return services.record_payout(
        vendor=vendor,
        amount=Decimal(amount),
        method="bank",
        reference=reference,
        actor=AdminFactory(),
    )


def balance_url(vendor):
    return f"/api/v1/admin/vendors/{vendor.pk}/balance/"


def body(vendor, amount="50000.00", **overrides):
    return {
        "vendor_id": str(vendor.pk),
        "amount": amount,
        "method": "bank",
        "reference": "TRX-1",
        "note": "November",
    } | overrides


@pytest.fixture
def vendor(db):
    return VendorProfileFactory()


@pytest.fixture
def admin_api(db, auth_client):
    return auth_client(AdminFactory())


# --- Permissions -----------------------------------------------------------


@pytest.mark.parametrize("url", [EARNINGS, PAYOUTS, COMMISSION, ADMIN_PAYOUTS])
def test_anonymous_is_rejected(db, api_client, url):
    assert api_client.get(url).status_code == 401


@pytest.mark.parametrize("url", [EARNINGS, PAYOUTS])
@pytest.mark.parametrize("factory", [ClientFactory, AdminFactory])
def test_vendor_endpoints_are_for_vendors(db, auth_client, url, factory):
    assert auth_client(factory()).get(url).status_code == 403


@pytest.mark.parametrize("factory", [ClientFactory, VendorUserFactory])
def test_admin_endpoints_are_for_admins(vendor, auth_client, factory):
    api = auth_client(factory())
    for url in (COMMISSION, ADMIN_PAYOUTS, balance_url(vendor)):
        assert api.get(url).status_code == 403
    assert api.post(COMMISSION, {"rate": "0.5"}).status_code == 403
    assert api.post(ADMIN_PAYOUTS, body(vendor)).status_code == 403
    assert CommissionSetting.objects.count() == 1
    assert not Payout.objects.exists()


def test_vendor_account_without_a_profile_gets_404(db, auth_client):
    api = auth_client(VendorUserFactory())
    assert api.get(EARNINGS).status_code == 404
    assert api.get(PAYOUTS).status_code == 404


# --- Vendor ----------------------------------------------------------------


def test_earnings_list_and_summary(auth_client, vendor):
    online = earn(vendor, "100000.00")
    cash = earn(vendor, "50000.00", **CASH)
    refunded = earn(vendor, "70000.00")
    services.reverse_earning(refunded.order)
    earn(VendorProfileFactory())  # another vendor
    pay_out(vendor)

    data = auth_client(vendor.user).get(EARNINGS).json()

    assert data["summary"] == {
        "gross": "150000.00",
        "commission": "15000.00",
        "net_online": "90000.00",
        "commission_owed_cash": "5000.00",
        "payouts": "20000.00",
        "balance": "65000.00",
    }
    assert data["count"] == 3
    rows = {row["id"]: row for row in data["results"]}
    assert set(rows) == {str(e.pk) for e in (online, cash, refunded)}
    assert rows[str(refunded.pk)]["reversed"] is True
    row = rows[str(online.pk)]
    assert row["order_reference"] == online.order.reference
    assert (row["gross"], row["commission_rate"]) == ("100000.00", "0.1000")
    assert (row["commission_amount"], row["net"]) == ("10000.00", "90000.00")


def test_summary_covers_all_pages(auth_client, vendor):
    earn(vendor)
    earn(vendor)
    data = auth_client(vendor.user).get(EARNINGS, {"page_size": 1}).json()
    assert len(data["results"]) == 1
    assert data["summary"]["gross"] == "200000.00"


def test_empty_summary(auth_client, vendor):
    data = auth_client(vendor.user).get(EARNINGS).json()
    assert data["results"] == []
    assert set(data["summary"].values()) == {"0.00"}


def test_suspended_vendor_still_sees_earnings(db, auth_client):
    vendor = VendorProfileFactory(status="suspended")
    earn(vendor)
    assert auth_client(vendor.user).get(EARNINGS).json()["count"] == 1


def test_vendor_sees_only_own_payouts(auth_client, vendor):
    for v in (vendor, VendorProfileFactory()):
        earn(v)
        pay_out(v, "100")
    data = auth_client(vendor.user).get(PAYOUTS).json()
    assert data["count"] == 1
    assert data["results"][0]["amount"] == "100.00"
    assert "recorded_by" not in data["results"][0]


# --- Commission ------------------------------------------------------------


def test_commission_current_rate_and_history(admin_api):
    CommissionSetting.objects.create(
        rate=Decimal("0.3"), effective_from=timezone.now() + timedelta(days=1)
    )
    data = admin_api.get(COMMISSION).json()
    assert data["current_rate"] == "0.1000"
    assert [row["rate"] for row in data["results"]] == ["0.3000", "0.1000"]


def test_rate_change_affects_only_later_payments(admin_api, vendor):
    before = earn(vendor)
    response = admin_api.post(COMMISSION, {"rate": "0.15"})
    assert response.status_code == 201
    assert response.json()["rate"] == "0.1500"
    assert CommissionSetting.objects.get(rate=Decimal("0.15")).set_by is not None
    before.refresh_from_db()
    assert before.commission_rate == Decimal("0.1")
    assert earn(vendor).commission_rate == Decimal("0.15")


@pytest.mark.parametrize("rate", ["-0.1", "1.01", "0.12345", "abc", "", "NaN"])
def test_invalid_rate(admin_api, rate):
    response = admin_api.post(COMMISSION, {"rate": rate})
    assert response.status_code == 400
    assert "rate" in response.json()["errors"]


# --- Payouts ---------------------------------------------------------------


def test_payout_reduces_balance(admin_api, vendor):
    earn(vendor)
    response = admin_api.post(ADMIN_PAYOUTS, body(vendor))
    assert response.status_code == 201
    data = response.json()
    assert (data["amount"], data["reference"]) == ("50000.00", "TRX-1")
    assert data["vendor"]["id"] == str(vendor.pk)
    payout = Payout.objects.get()
    assert payout.recorded_by.role == "admin"
    assert payout.paid_at <= timezone.now()
    assert admin_api.get(balance_url(vendor)).json()["balance"] == "40000.00"
    assert admin_api.get(ADMIN_PAYOUTS).json()["count"] == 1


def test_payout_of_the_whole_balance(admin_api, vendor):
    earn(vendor)
    assert admin_api.post(ADMIN_PAYOUTS, body(vendor, "90000.00")).status_code == 201
    assert services.vendor_balance(vendor) == 0


def test_suspended_vendor_can_be_paid(admin_api):
    vendor = VendorProfileFactory(status="suspended")
    earn(vendor)
    assert admin_api.post(ADMIN_PAYOUTS, body(vendor)).status_code == 201


def test_over_balance_is_rejected(admin_api, vendor):
    earn(vendor)
    response = admin_api.post(ADMIN_PAYOUTS, body(vendor, "90000.01"))
    assert response.status_code == 400
    assert "amount" in response.json()["errors"]
    assert not Payout.objects.exists()


def test_negative_balance_cannot_be_paid(admin_api, vendor):
    earn(vendor, "50000.00", **CASH)
    assert admin_api.get(balance_url(vendor)).json()["balance"] == "-5000.00"
    assert admin_api.post(ADMIN_PAYOUTS, body(vendor, "0.01")).status_code == 400


def test_repeated_reference_conflicts(admin_api, vendor):
    earn(vendor)
    assert admin_api.post(ADMIN_PAYOUTS, body(vendor, "90000")).status_code == 201
    # A conflict even though the balance is now too low as well: it is the clearer answer.
    response = admin_api.post(ADMIN_PAYOUTS, body(vendor, "90000"))
    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_payout"
    assert Payout.objects.count() == 1


def test_same_reference_for_another_vendor_is_fine(admin_api, vendor):
    for v in (vendor, VendorProfileFactory()):
        earn(v)
        assert admin_api.post(ADMIN_PAYOUTS, body(v)).status_code == 201


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0"),
        ("amount", "-5"),
        ("amount", "1.001"),
        ("method", "cheque"),
        ("reference", ""),
        ("vendor_id", NO_ID),
    ],
)
def test_invalid_payout(admin_api, vendor, field, value):
    earn(vendor)
    response = admin_api.post(ADMIN_PAYOUTS, body(vendor, **{field: value}))
    assert response.status_code == 400
    assert field in response.json()["errors"]


def test_balance_of_unknown_vendor(admin_api):
    assert admin_api.get(f"/api/v1/admin/vendors/{NO_ID}/balance/").status_code == 404


# --- Concurrency (committed rows, removed by hand as in payments) ----------


@pytest.fixture
def committed(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        earning = earn(VendorProfileFactory())
        vendor, order, admin = earning.vendor, earning.order, AdminFactory()
        yield vendor, admin
        Payout.objects.filter(vendor=vendor).delete()
        VendorEarning.objects.filter(vendor=vendor).delete()
        Payment.objects.filter(order=order).delete()
        Order.objects.filter(pk=order.pk).delete()
        User.objects.filter(pk__in=[order.client_id, vendor.user_id, admin.pk]).delete()
        connection.close()


def test_concurrent_payouts_cannot_exceed_the_balance(committed):
    vendor, admin = committed
    barrier = Barrier(4)

    def pay(n):
        try:
            barrier.wait(timeout=10)
            return services.record_payout(
                vendor=vendor,
                amount=Decimal("60000"),
                method="bank",
                reference=f"T{n}",
                actor=admin,
            )
        except ValidationError as exc:
            return exc
        finally:
            connection.close()

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(pay, range(4)))
    assert sum(isinstance(r, Payout) for r in results) == 1
    assert services.vendor_balance(vendor) == Decimal("30000.00")
