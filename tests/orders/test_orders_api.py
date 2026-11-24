from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders.models import Order
from tests.factories import (
    AdminFactory,
    ClientFactory,
    EventFactory,
    ItemFactory,
    OrderFactory,
    OrderLineFactory,
    PaymentFactory,
    VendorProfileFactory,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/orders/"


def url(order, action=""):
    return f"{URL}{order.pk}/" + (f"{action}/" if action else "")


def payload(event, item, **overrides):
    return {
        "event_id": str(event.pk),
        "vendor_id": str(item.vendor_id),
        "lines": [{"item_id": str(item.pk), "quantity": 10}],
    } | overrides


class TestCreate:
    def test_success_ignores_client_total(self, auth_client):
        event, item = EventFactory(), ItemFactory()
        response = auth_client(event.client).post(
            URL, payload(event, item, total="1.00", status="paid"), format="json"
        )
        assert response.status_code == 201, response.data
        body = response.json()
        assert (body["total"], body["status"]) == ("150000.00", "pending")
        assert body["lines"][0]["name"] == item.name
        assert body["payments"] == []
        assert body["status_history"][0]["to_status"] == "pending"

    def test_validation(self, auth_client):
        event, item = EventFactory(), ItemFactory()
        client = auth_client(event.client)
        for override in ({"lines": []}, {"event_id": "x"}, {"lines": [{"quantity": 0}]}):
            response = client.post(URL, payload(event, item, **override), format="json")
            assert response.status_code == 400

    def test_alcohol_without_confirmation(self, auth_client):
        event, item = EventFactory(), ItemFactory(kind="drink", is_alcoholic=True)
        response = auth_client(event.client).post(URL, payload(event, item), format="json")
        assert response.status_code == 400
        assert "age_confirmed" in response.json()["errors"]

    def test_permissions(self, api_client, auth_client):
        event, item = EventFactory(), ItemFactory()
        assert api_client.post(URL, payload(event, item), format="json").status_code == 401
        for user in (item.vendor.user, AdminFactory()):
            response = auth_client(user).post(URL, payload(event, item), format="json")
            assert response.status_code == 403


class TestRead:
    def test_scoping(self, auth_client):
        order, other = OrderFactory(), OrderFactory()
        for user in (order.client, order.vendor.user):
            client = auth_client(user)
            assert [o["id"] for o in client.get(URL).json()["results"]] == [str(order.pk)]
            assert client.get(url(order)).status_code == 200
            assert client.get(url(other)).status_code == 404
        assert auth_client(AdminFactory()).get(URL).json()["count"] == 2

    def test_anonymous(self, api_client):
        assert api_client.get(URL).status_code == 401
        assert api_client.get(url(OrderFactory())).status_code == 401

    def test_filters(self, auth_client):
        owner = ClientFactory()
        first = OrderFactory(client=owner)
        OrderFactory(client=owner, status="paid")
        client = auth_client(owner)
        for params in ({"status": "pending"}, {"event": str(first.event_id)}):
            body = client.get(URL, params).json()
            assert [o["id"] for o in body["results"]] == [str(first.pk)]
        assert client.get(URL, {"status": "bogus"}).status_code == 400

    def test_detail_hides_sensitive_payment_fields(self, auth_client):
        payment = PaymentFactory(raw_callback={"secret": "x"})
        OrderLineFactory(order=payment.order)
        body = auth_client(payment.order.vendor.user).get(url(payment.order)).json()
        assert len(body["lines"]) == len(body["payments"]) == 1
        assert not {"raw_callback", "payer_phone", "needs_review"} & set(body["payments"][0])

    def test_list_query_count_is_constant(self, auth_client, django_assert_max_num_queries):
        vendor = VendorProfileFactory()
        for _ in range(5):
            OrderLineFactory(order=OrderFactory(vendor=vendor))
        client = auth_client(vendor.user)
        with django_assert_max_num_queries(8):
            assert client.get(URL).json()["count"] == 5

    def test_immutable_via_rest(self, auth_client):
        order = OrderFactory()
        client = auth_client(order.client)
        assert client.patch(url(order), {"total": "1"}, format="json").status_code == 405
        assert client.delete(url(order)).status_code == 405


ACTIONS = {  # action: (from, to, allowed roles)
    "confirm": ("pending", "confirmed", {"vendor", "admin"}),
    "decline": ("pending", "declined", {"vendor", "admin"}),
    "cancel": ("confirmed", "cancelled", {"client", "admin"}),
    "fulfil": ("paid", "fulfilled", {"vendor", "admin"}),
    "complete": ("fulfilled", "completed", {"vendor", "admin"}),
}


class TestActions:
    def make(self, status):
        client = ClientFactory()
        event = EventFactory(client=client, starts_at=timezone.now() - timedelta(days=1))
        return OrderFactory(client=client, event=event, status=status)

    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize("role", ["client", "vendor", "admin"])
    def test_roles(self, auth_client, action, role):
        source, target, allowed = ACTIONS[action]
        order = self.make(source)
        user = {"client": order.client, "vendor": order.vendor.user}.get(role) or AdminFactory()
        response = auth_client(user).post(url(order, action), {"reason": "Busy"}, format="json")
        assert response.status_code == (200 if role in allowed else 403), response.data
        order.refresh_from_db()
        assert order.status == (target if role in allowed else source)

    @pytest.mark.parametrize("action", ACTIONS)
    def test_invalid_state_is_409(self, auth_client, action):
        order = self.make("refunded")
        response = auth_client(AdminFactory()).post(
            url(order, action), {"reason": "x"}, format="json"
        )
        assert response.status_code == 409
        assert response.json()["code"] == "invalid_state"

    @pytest.mark.parametrize("action", ACTIONS)
    def test_out_of_scope_and_anonymous(self, api_client, auth_client, action):
        order = self.make(ACTIONS[action][0])
        assert api_client.post(url(order, action)).status_code == 401
        stranger = ClientFactory() if action == "cancel" else VendorProfileFactory().user
        response = auth_client(stranger).post(url(order, action), {"reason": "x"}, format="json")
        assert response.status_code == 404
        assert Order.objects.get().status == ACTIONS[action][0]

    def test_decline_needs_reason_and_records_it(self, auth_client):
        order = OrderFactory()
        client = auth_client(order.vendor.user)
        assert client.post(url(order, "decline"), {}, format="json").status_code == 400
        body = client.post(url(order, "decline"), {"reason": "Booked"}, format="json").json()
        assert body["status_history"][-1]["note"] == "Booked"


class TestEventRules:
    @pytest.mark.parametrize("status", Order.Status.values)
    def test_delete(self, auth_client, status):
        order = OrderFactory(status=status)
        response = auth_client(order.client).delete(f"/api/v1/events/{order.event_id}/")
        if status in ("cancelled", "declined", "expired"):
            assert response.status_code == 204
            order.refresh_from_db()
            assert order.event is None
        else:
            assert response.status_code == 409

    @pytest.mark.parametrize(("status", "code"), [("pending", 409), ("cancelled", 200)])
    def test_reschedule(self, auth_client, status, code):
        order = OrderFactory(status=status)
        client = auth_client(order.client)
        path = f"/api/v1/events/{order.event_id}/"
        when = (timezone.now() + timedelta(days=1)).isoformat()
        assert client.patch(path, {"starts_at": when}, format="json").status_code == code
        assert client.patch(path, {"notes": "ok"}, format="json").status_code == 200
