from datetime import timedelta
from itertools import product

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.common.exceptions import Conflict
from apps.orders import services
from apps.orders.models import Order, OrderStatusChange
from tests.factories import AdminFactory, ClientFactory, EventFactory, OrderFactory, PaymentFactory

pytestmark = pytest.mark.django_db

# Written out by hand from data-model.md, so the code's own table is not its own oracle.
EXPECTED = {
    ("pending", "confirmed"): {"vendor", "admin"},
    ("pending", "declined"): {"vendor", "admin"},
    ("pending", "expired"): {"system"},
    ("pending", "cancelled"): {"client", "admin"},
    ("confirmed", "cancelled"): {"client", "admin"},
    ("awaiting_cash", "cancelled"): {"client", "admin"},
    ("confirmed", "awaiting_cash"): {"client"},
    ("confirmed", "paid"): {"system"},
    ("awaiting_cash", "paid"): {"system", "vendor", "admin"},
    ("paid", "fulfilled"): {"vendor", "admin"},
    ("fulfilled", "completed"): {"vendor", "admin", "system"},
    ("paid", "refunded"): {"admin"},
    ("fulfilled", "refunded"): {"admin"},
    ("completed", "refunded"): {"admin"},
}
ROLES = ("client", "vendor", "admin", "system")


def actor_for(role, order):
    return {
        "client": lambda: order.client,
        "vendor": lambda: order.vendor.user,
        "admin": AdminFactory,
        "system": lambda: None,
    }[role]()


def past_event_order(**kwargs):
    client = ClientFactory()
    event = EventFactory(client=client, starts_at=timezone.now() - timedelta(days=1))
    return OrderFactory(client=client, event=event, **kwargs)


@pytest.mark.parametrize(
    ("source", "target", "role"), list(product(Order.Status.values, Order.Status.values, ROLES))
)
def test_full_matrix(source, target, role):
    order = past_event_order(status=source)
    actor = actor_for(role, order)
    allowed = EXPECTED.get((source, target))
    if allowed and role in allowed:
        result = services.transition(order, target, actor, note="n")
        assert result.status == target
        change = OrderStatusChange.objects.get()
        assert (change.from_status, change.to_status) == (source, target)
        assert (change.actor, change.note) == (actor, "n")
    else:
        with pytest.raises(PermissionDenied if allowed else Conflict):
            services.transition(order, target, actor)
        order.refresh_from_db()
        assert order.status == source
        assert not OrderStatusChange.objects.exists()


@pytest.mark.parametrize("stranger", ["client", "vendor"])
def test_unrelated_user_is_forbidden(stranger):
    order, other = OrderFactory(), OrderFactory()
    with pytest.raises(PermissionDenied):
        services.transition(order, "confirmed", actor_for(stranger, other))


def test_stale_instance_uses_database_state():
    order = OrderFactory()
    Order.objects.filter(pk=order.pk).update(status="cancelled")
    with pytest.raises(Conflict):
        services.transition(order, "confirmed", order.vendor.user)


def test_cannot_confirm_after_deadline():
    order = OrderFactory(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(Conflict):
        services.transition(order, "confirmed", order.vendor.user)


def test_suspended_vendor_can_decline_but_not_confirm():
    order = OrderFactory(vendor__status="suspended")
    with pytest.raises(Conflict):
        services.transition(order, "confirmed", order.vendor.user)
    assert services.transition(order, "declined", order.vendor.user).status == "declined"


def test_cannot_complete_before_event():
    order = OrderFactory(status="fulfilled")
    with pytest.raises(Conflict):
        services.transition(order, "completed", order.vendor.user)


def test_cancel_blocked_by_recent_online_payment():
    payment = PaymentFactory()
    with pytest.raises(Conflict) as exc:
        services.transition(payment.order, "cancelled", payment.order.client)
    assert exc.value.get_codes() == "payment_in_progress"


def test_cancel_allowed_when_online_payment_is_stale():
    payment = PaymentFactory()
    type(payment).objects.update(created_at=timezone.now() - timedelta(minutes=31))
    assert services.transition(payment.order, "cancelled", payment.order.client)


def test_cancel_cancels_pending_cash():
    payment = PaymentFactory(order__status="awaiting_cash", method="cash", provider="cash")
    services.transition(payment.order, "cancelled", payment.order.client)
    payment.refresh_from_db()
    assert payment.status == "cancelled"
