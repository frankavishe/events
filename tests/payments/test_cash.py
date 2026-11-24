import pytest

from apps.ledger.models import VendorEarning
from apps.ledger.services import vendor_balance
from apps.payments import services
from tests.factories import AdminFactory, OrderFactory, PaymentFactory, VendorProfileFactory

pytestmark = pytest.mark.django_db


def url(order, action="confirm-cash"):
    return f"/api/v1/orders/{order.pk}/{action}/"


@pytest.fixture
def payment():
    return PaymentFactory(order__status="awaiting_cash", method="cash", provider="cash")


@pytest.mark.parametrize("role", ["vendor", "admin"])
def test_confirm(auth_client, payment, role):
    order = payment.order
    user = order.vendor.user if role == "vendor" else AdminFactory()
    response = auth_client(user).post(url(order))
    assert response.status_code == 200, response.data
    assert response.json()["status"] == "paid"
    payment.refresh_from_db()
    assert (payment.status, payment.confirmed_by) == ("success", user)
    assert payment.completed_at
    assert VendorEarning.objects.get().channel == "cash"
    assert vendor_balance(order.vendor) == -order.total / 10
    assert order.status_changes.get().actor == user
    assert auth_client(user).post(url(order)).status_code == 409
    assert VendorEarning.objects.count() == 1


def test_forbidden(api_client, auth_client, payment):
    order = payment.order
    assert api_client.post(url(order)).status_code == 401
    for user in (order.client, VendorProfileFactory().user):
        assert auth_client(user).post(url(order)).status_code == 403
    payment.refresh_from_db()
    assert payment.status == "pending"


def test_not_awaiting_cash(auth_client):
    order = OrderFactory(status="confirmed")
    assert auth_client(order.vendor.user).post(url(order)).status_code == 409


def test_unknown_order(auth_client):
    path = "/api/v1/orders/11111111-1111-1111-1111-111111111111/confirm-cash/"
    assert auth_client(AdminFactory()).post(path).status_code == 404


class TestRefund:
    def test_admin(self, auth_client, payment):
        order = payment.order
        services.confirm_cash(order.pk, order.vendor.user)
        client = auth_client(AdminFactory())
        assert client.post(url(order, "refund"), {}, format="json").status_code == 400
        response = client.post(url(order, "refund"), {"note": "Rain"}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "refunded"
        assert VendorEarning.objects.get().reversed
        assert vendor_balance(order.vendor) == 0
        again = client.post(url(order, "refund"), {"note": "x"}, format="json")
        assert again.status_code == 409

    def test_denied(self, api_client, auth_client):
        order = OrderFactory(status="paid")
        assert api_client.post(url(order, "refund")).status_code == 401
        for user in (order.client, order.vendor.user):
            response = auth_client(user).post(url(order, "refund"), {"note": "x"}, format="json")
            assert response.status_code == 403

    def test_unpaid(self, auth_client):
        order = OrderFactory(status="confirmed")
        response = auth_client(AdminFactory()).post(
            url(order, "refund"), {"note": "x"}, format="json"
        )
        assert response.status_code == 409
