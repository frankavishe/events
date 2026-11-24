from datetime import timedelta

import pytest
from django.core import serializers
from django.utils import timezone

from apps.common.exceptions import GatewayError
from apps.payments import services
from apps.payments.models import Payment
from tests.factories import AdminFactory, ClientFactory, OrderFactory, PaymentFactory

pytestmark = pytest.mark.django_db

MOBILE = {"method": "online", "provider": "mpesa", "phone": "0712345678"}
BANK = {
    "method": "online",
    "provider": "bank",
    "bank_name": "CRDB",
    "account_number": "0150999888",
    "phone": "0712345678",
    "otp": "987654",
}


def url(order):
    return f"/api/v1/orders/{order.pk}/pay/"


@pytest.fixture
def order():
    return OrderFactory(status="confirmed")


@pytest.fixture
def down(monkeypatch):
    class Down:
        def checkout_mobile(self, **kwargs):
            raise GatewayError

        checkout_bank = checkout_mobile

    monkeypatch.setattr(services, "get_gateway", Down)


class TestOnline:
    def test_mobile(self, auth_client, order):
        response = auth_client(order.client).post(
            url(order), MOBILE | {"amount": "1"}, format="json"
        )
        assert response.status_code == 202, response.data
        payment = Payment.objects.get()
        assert response.json() == {
            "payment_id": str(payment.pk),
            "status": "pending",
            "order_status": "confirmed",
        }
        assert (payment.amount, payment.payer_phone) == (order.total, "+255712345678")
        assert payment.gateway_reference

    def test_bank_never_stores_otp_or_account(self, auth_client, order, caplog):
        response = auth_client(order.client).post(url(order), BANK, format="json")
        assert response.status_code == 202, response.data
        payment = Payment.objects.get()
        assert (payment.provider, payment.bank_name) == ("bank", "CRDB")
        # Random identifiers are excluded: they could contain the digits by chance.
        stored = serializers.serialize(
            "json",
            [payment],
            fields=["payer_phone", "bank_name", "raw_callback", "review_reason"],
        )
        dump = stored.replace(str(payment.pk), "") + caplog.text
        assert BANK["otp"] not in dump
        assert BANK["account_number"] not in dump

    def test_allowed_from_awaiting_cash(self, auth_client):
        order = OrderFactory(status="awaiting_cash")
        assert auth_client(order.client).post(url(order), MOBILE, format="json").status_code == 202

    def test_in_progress_then_stale(self, auth_client, order):
        old = PaymentFactory(order=order)
        client = auth_client(order.client)
        response = client.post(url(order), MOBILE, format="json")
        assert response.status_code == 409
        assert response.json()["code"] == "payment_in_progress"
        Payment.objects.update(created_at=timezone.now() - timedelta(minutes=31))
        assert client.post(url(order), MOBILE, format="json").status_code == 202
        old.refresh_from_db()
        assert old.status == "failed"

    def test_retry_after_failure(self, auth_client, order):
        PaymentFactory(order=order, status="failed")
        assert auth_client(order.client).post(url(order), MOBILE, format="json").status_code == 202

    @pytest.mark.parametrize("body", [MOBILE, BANK])
    def test_gateway_down(self, auth_client, order, down, body):
        client = auth_client(order.client)
        response = client.post(url(order), body, format="json")
        assert response.status_code == 502
        assert response.json()["code"] == "gateway_error"
        assert Payment.objects.get().status == "failed"
        order.refresh_from_db()
        assert order.status == "confirmed"
        assert client.post(url(order), {"method": "cash"}, format="json").status_code == 200

    def test_unexpected_gateway_crash_leaves_order_payable(self, auth_client, order, monkeypatch):
        class Broken:
            def checkout_mobile(self, **kwargs):
                raise RuntimeError("bug")

        monkeypatch.setattr(services, "get_gateway", Broken)
        client = auth_client(order.client)
        client.raise_request_exception = False
        assert client.post(url(order), MOBILE, format="json").status_code == 500
        assert Payment.objects.get().status == "failed"


class TestCash:
    def test_cash(self, auth_client, order):
        client = auth_client(order.client)
        response = client.post(url(order), {"method": "cash"}, format="json")
        assert response.status_code == 200
        assert response.json()["order_status"] == "awaiting_cash"
        payment = Payment.objects.get()
        assert (payment.method, payment.provider, payment.status) == ("cash", "cash", "pending")
        assert client.post(url(order), {"method": "cash"}, format="json").status_code == 409

    def test_blocked_while_online_pending(self, auth_client, order):
        PaymentFactory(order=order)
        response = auth_client(order.client).post(url(order), {"method": "cash"}, format="json")
        assert response.status_code == 409


@pytest.mark.parametrize(
    "status", ["pending", "declined", "expired", "cancelled", "paid", "completed", "refunded"]
)
@pytest.mark.parametrize("body", [MOBILE, {"method": "cash"}])
def test_not_payable_states(auth_client, status, body):
    order = OrderFactory(status=status)
    assert auth_client(order.client).post(url(order), body, format="json").status_code == 409
    assert not Payment.objects.exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "method"),
        ({"method": "gold"}, "method"),
        ({"method": "online"}, "provider"),
        (MOBILE | {"provider": "cash"}, "provider"),
        ({"method": "online", "provider": "mpesa"}, "phone"),
        (MOBILE | {"phone": "12"}, "phone"),
        ({k: v for k, v in BANK.items() if k != "otp"}, "otp"),
        ({k: v for k, v in BANK.items() if k != "account_number"}, "account_number"),
        (BANK | {"bank_name": "XYZ"}, "bank_name"),
    ],
)
def test_validation(auth_client, order, body, field):
    response = auth_client(order.client).post(url(order), body, format="json")
    assert response.status_code == 400
    assert field in response.json()["errors"]


def test_permissions(api_client, auth_client, order):
    assert api_client.post(url(order), MOBILE, format="json").status_code == 401
    for user in (order.vendor.user, AdminFactory()):
        assert auth_client(user).post(url(order), MOBILE, format="json").status_code == 403
    assert auth_client(ClientFactory()).post(url(order), MOBILE, format="json").status_code == 404


def test_payment_detail_scoping(api_client, auth_client):
    payment = PaymentFactory()
    path = f"/api/v1/payments/{payment.pk}/"
    assert api_client.get(path).status_code == 401
    for user in (payment.order.client, payment.order.vendor.user, AdminFactory()):
        body = auth_client(user).get(path).json()
        assert (body["id"], body["status"]) == (str(payment.pk), "pending")
    assert auth_client(OrderFactory().client).get(path).status_code == 404
