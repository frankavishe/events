import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ledger.models import VendorEarning
from apps.orders import services as orders
from apps.payments.models import Payment
from apps.payments.tasks import reconcile_pending_payments
from tests.factories import PaymentFactory

pytestmark = pytest.mark.django_db
TOKEN = "test-callback-token"


def url(token=TOKEN):
    return f"/api/v1/webhooks/azampay/{token}/"


@pytest.fixture
def payment():
    return PaymentFactory()


@pytest.fixture
def send(api_client):
    def _send(payment, **overrides):
        body = {
            "msisdn": "255712345678",
            "amount": "150000",
            "message": "m",
            "utilityref": str(payment.pk),
            "operator": "Mpesa",
            "reference": "AZ-1",
            "transactionstatus": "success",
            "submerchantAcc": None,
        } | overrides
        response = api_client.post(url(), body, format="json")
        assert response.status_code == 200
        payment.refresh_from_db()
        payment.order.refresh_from_db()
        return payment

    return _send


def assert_flagged(payment, reason):
    assert (payment.status, payment.needs_review, payment.review_reason) == ("failed", True, reason)
    assert not VendorEarning.objects.filter(payment=payment).exists()


@pytest.mark.parametrize("configured", [TOKEN, ""])
def test_bad_token(api_client, settings, payment, configured):
    settings.AZAMPAY_CALLBACK_TOKEN = configured
    body = {"utilityref": str(payment.pk), "amount": "150000", "transactionstatus": "success"}
    for path in (url("wrong"), url("%C3%A9"), "/api/v1/webhooks/azampay//"):
        assert api_client.post(path, body, format="json").status_code == 404
    payment.refresh_from_db()
    assert payment.status == "pending"


def test_success_and_duplicate(send, payment):
    send(payment)
    assert (payment.status, payment.gateway_reference) == ("success", "AZ-1")
    assert payment.completed_at
    assert payment.raw_callback["operator"] == "Mpesa"
    assert payment.order.status == "paid"
    send(payment)
    assert VendorEarning.objects.count() == 1
    assert payment.order.status_changes.count() == 1
    assert payment.order.status_changes.get().actor is None


def test_status_is_case_insensitive(send, payment):
    assert send(payment, transactionstatus="Success").status == "success"


def test_failure_then_late_success(send, payment):
    send(payment, transactionstatus="failure")
    assert payment.status == "failed"
    assert payment.order.status == "confirmed"
    send(payment)
    assert payment.status == "success"
    assert payment.order.status == "paid"


def test_failure_after_success_ignored(send, payment):
    send(payment)
    send(payment, transactionstatus="failure")
    assert payment.status == "success"
    assert payment.raw_callback["transactionstatus"] == "success"


@pytest.mark.parametrize("amount", ["149999", "", "abc", "NaN", "1e999999", None, [], True])
def test_amount_mismatch(send, payment, amount):
    send(payment, amount=amount)
    assert_flagged(payment, "amount_mismatch")
    assert payment.order.status == "confirmed"


@pytest.mark.parametrize("amount", ["150000.00", 150000, 150000.0])
def test_equivalent_amounts(send, payment, amount):
    assert send(payment, amount=amount).status == "success"


def test_unknown_status_ignored(send, payment):
    assert send(payment, transactionstatus="processing").status == "pending"


def test_unknown_or_malformed_payload(api_client):
    for body in (
        {"utilityref": str(uuid.uuid4()), "transactionstatus": "success"},
        {"utilityref": "nope"},
        {"utilityref": {"a": 1}},
        {},
        [],
        "text",
    ):
        assert api_client.post(url(), body, format="json").status_code == 200
    bad = api_client.post(url(), "{bad", content_type="application/json")
    assert bad.status_code == 400


def test_cash_payment_cannot_be_settled_by_callback(send):
    payment = PaymentFactory(order__status="awaiting_cash", method="cash", provider="cash")
    assert send(payment).status == "pending"


def test_success_cancels_pending_cash(send):
    payment = PaymentFactory(order__status="awaiting_cash")
    cash = PaymentFactory(order=payment.order, method="cash", provider="cash")
    send(payment)
    cash.refresh_from_db()
    assert cash.status == "cancelled"
    assert VendorEarning.objects.get().channel == "online"


def test_late_success_after_cancel(send, payment):
    Payment.objects.update(created_at=timezone.now() - timedelta(minutes=31))
    orders.transition(payment.order, "cancelled", payment.order.client)
    send(payment)
    assert_flagged(payment, "order_not_payable")
    assert payment.order.status == "cancelled"


def test_second_success_for_paid_order(send, payment):
    other = PaymentFactory(order=payment.order, status="failed")
    send(payment)
    send(other, reference="AZ-2")
    assert_flagged(other, "order_not_payable")
    assert VendorEarning.objects.count() == 1


def test_reference_reused_by_other_payment(send, payment):
    send(payment)
    other = send(PaymentFactory())
    assert_flagged(other, "duplicate_reference")


def test_reconcile_flags_only_stale_pending_online(send):
    stale, fresh = PaymentFactory(), PaymentFactory()
    cash = PaymentFactory(order__status="awaiting_cash", method="cash", provider="cash")
    old = timezone.now() - timedelta(minutes=31)
    Payment.objects.filter(pk__in=[stale.pk, cash.pk]).update(created_at=old)
    assert reconcile_pending_payments() == 1
    assert reconcile_pending_payments() == 0
    for payment in (stale, fresh, cash):
        payment.refresh_from_db()
    assert (stale.status, stale.needs_review, stale.review_reason) == (
        "pending",
        True,
        "no_callback",
    )
    assert not fresh.needs_review
    assert not cash.needs_review
    send(stale)
    assert (stale.status, stale.needs_review, stale.review_reason) == ("success", False, "")
