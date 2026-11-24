from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import transaction
from django.utils import timezone

from apps.chatbot.models import ChatMessage, Conversation
from apps.notifications import tasks
from apps.notifications.clients import FakeMessagingClient, MessagingError
from apps.orders import services as orders
from apps.payments import services as payments
from tests.factories import ClientFactory, EventFactory, ItemFactory, OrderFactory, PaymentFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def outbox(settings):
    settings.WHATSAPP_TEMPLATE_NEW_ORDER = "new_order"
    settings.WHATSAPP_TEMPLATE_ORDER_STATUS = "order_status"
    settings.WHATSAPP_TEMPLATE_PAYMENT_FAILED = "payment_failed"
    FakeMessagingClient.reset()
    yield FakeMessagingClient.outbox
    FakeMessagingClient.reset()


def open_window(phone, hours=1):
    return Conversation.objects.create(
        wa_id=phone.lstrip("+"), last_inbound_at=timezone.now() - timedelta(hours=hours)
    )


def place():
    item, client = ItemFactory(), ClientFactory()
    return orders.create_order(
        client=client,
        event_id=EventFactory(client=client).pk,
        vendor_id=item.vendor_id,
        lines=[{"item_id": item.pk, "quantity": 2}],
    )


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    return lambda: django_capture_on_commit_callbacks(execute=True)


def test_new_order_goes_to_the_vendor_as_template(commit, outbox):
    with commit():
        order = place()
    (message,) = outbox
    assert message["phone"] == order.vendor.contact_phone.lstrip("+")
    assert (message["template"], message["language"]) == ("new_order", "en")
    assert order.reference in message["params"]
    assert "TZS 30,000" in message["params"]


@pytest.mark.parametrize(("hours", "free"), [(23, True), (25, False)])
def test_24h_window(commit, outbox, hours, free):
    order = OrderFactory()
    conversation = open_window(order.client.phone, hours)
    with commit():
        orders.transition(order, "confirmed", order.vendor.user)
    assert (outbox[0]["template"] is None) is free
    assert ChatMessage.objects.get().conversation == conversation


def test_status_text_in_preferred_language(commit, outbox):
    order = OrderFactory(client=ClientFactory(preferred_language="sw"))
    open_window(order.client.phone)
    with commit():
        orders.transition(order, "confirmed", order.vendor.user)
    assert "imethibitishwa" in outbox[0]["text"]
    assert order.reference in outbox[0]["text"]


def test_decline_reason_reaches_the_client(commit, outbox):
    order = OrderFactory()
    open_window(order.client.phone)
    with commit():
        orders.transition(order, "declined", order.vendor.user, "Fully booked")
    assert "Fully booked" in outbox[0]["text"]


def test_clients_own_actions_are_not_echoed(commit, outbox):
    order = OrderFactory()
    with commit():
        orders.transition(order, "cancelled", order.client)
    assert outbox == []


def test_expiry_notifies(commit, outbox):
    OrderFactory(expires_at=timezone.now() - timedelta(minutes=1))
    with commit():
        orders.expire_overdue()
    assert len(outbox) == 1


def result(payment, success):
    return payments.handle_gateway_result(
        payment.pk, success=success, amount=Decimal("150000"), reference="r", raw={}
    )


def test_payment_results(commit, outbox):
    failed, paid = PaymentFactory(), PaymentFactory()
    with commit():
        result(failed, False)
        result(failed, False)  # repeated callback
    assert [m["template"] for m in outbox] == ["payment_failed"]
    with commit():
        result(paid, True)
        result(paid, True)
    assert [m["template"] for m in outbox] == ["payment_failed", "order_status"]


def test_no_template_is_skipped(commit, outbox, settings):
    settings.WHATSAPP_TEMPLATE_NEW_ORDER = ""
    with commit():
        place()
    assert outbox == []


def test_rollback_sends_nothing(commit, outbox):
    with commit(), pytest.raises(RuntimeError), transaction.atomic():
        place()
        raise RuntimeError
    assert outbox == []


def test_broker_failure_leaves_the_order(commit):
    with (
        patch.object(tasks.notify_new_order, "delay", side_effect=OSError("broker")),
        commit(),
    ):
        order = place()
    order.refresh_from_db()
    assert order.status == "pending"


@pytest.mark.parametrize(("transient", "attempts"), [(True, 4), (False, 1)])
def test_only_transient_errors_are_retried(transient, attempts):
    order = OrderFactory()
    with (
        patch.object(
            FakeMessagingClient, "send_template", side_effect=MessagingError(transient=transient)
        ) as send,
    ):
        # Propagation is off only here: it makes Celery raise instead of retrying eagerly.
        conf = tasks.notify_new_order.app.conf
        conf.task_eager_propagates = False
        try:
            tasks.notify_new_order.apply(args=[str(order.pk)], throw=False)
        finally:
            conf.task_eager_propagates = True
    assert send.call_count == attempts


def test_deleted_records_are_ignored(outbox):
    missing = "11111111-1111-1111-1111-111111111111"
    for task in (tasks.notify_new_order, tasks.notify_status, tasks.notify_payment_failed):
        task(missing)
    assert outbox == []
