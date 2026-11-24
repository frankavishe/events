import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.chatbot import services, tools
from apps.chatbot.models import ChatMessage
from apps.common.exceptions import GatewayError
from apps.events.models import Event
from apps.orders.models import Order
from tests.factories import (
    AdminFactory,
    CategoryFactory,
    ClientFactory,
    EventFactory,
    ItemFactory,
    OrderFactory,
    PackageFactory,
    ServiceAreaFactory,
    VendorProfileFactory,
    VendorUserFactory,
)

pytestmark = pytest.mark.django_db
PHONE = "+255712345678"


@pytest.fixture
def me(db):
    return ClientFactory(phone=PHONE)


@pytest.fixture
def use(conversation, inbound):
    """Run a tool in a new inbound message (or the given one)."""

    def run(name, message=None, **args):
        conversation.refresh_from_db()
        services.identify(conversation)
        return tools.run(name, args, conversation, message or inbound())

    return run


@pytest.fixture
def answered(conversation, inbound):
    """An inbound message the assistant has really replied to."""

    def make(message):
        return ChatMessage.objects.create(
            conversation=conversation,
            direction="out",
            role="model",
            reply_to=message,
            text="Total is ... confirm?",
            payload={"raw": None},
            status="sent",
        )

    return make


def test_declarations_match_implementations():
    names = [d["name"] for d in tools.DECLARATIONS]
    assert set(names) == set(tools.TOOLS)
    assert len(names) == len(set(names)) == 11
    for declaration in tools.DECLARATIONS:
        assert "user_id" not in declaration["parameters"]["properties"]


# --- Catalog ----------------------------------------------------------------


def test_search_items_and_packages(use):
    item = ItemFactory(name="Pilau")
    package = PackageFactory(name="Pilau package", items=[ItemFactory(name="Rice")])
    ItemFactory(name="Pilau hidden", is_available=False)
    results = use("search_catalog", query="pilau")["results"]
    assert {r["id"] for r in results} == {str(item.pk), str(package.pk)}
    assert {r["price"] for r in results} == {"TZS 15,000", "TZS 25,000"}


def test_search_filters(use):
    area = ServiceAreaFactory(name="Kinondoni")
    vendor = VendorProfileFactory(service_areas=[area])
    beer = ItemFactory(name="Beer", kind="drink", is_alcoholic=True, vendor=vendor)
    ItemFactory(name="Soda", kind="drink", unit_price=Decimal("90000"))

    def ids(**args):
        return [r["id"] for r in use("search_catalog", **args)["results"]]

    assert ids(alcoholic=True) == [str(beer.pk)]
    assert ids(service_area="kinondoni", kind="drink") == [str(beer.pk)]
    assert ids(max_price=20000) == [str(beer.pk)]


def test_search_by_swahili_category_and_single_word(use):
    category = CategoryFactory(kind="drink", name_en="Soft drinks", name_sw="Vinywaji baridi")
    item = ItemFactory(name="Fanta", kind="drink", category=category)
    for query in ("vinywaji", "fanta orange"):
        assert use("search_catalog", query=query)["results"][0]["id"] == str(item.pk)


def test_search_without_match_offers_alternatives(use):
    item = ItemFactory(name="Pilau")
    result = use("search_catalog", query="sushi")
    assert result["results"] == []
    assert result["alternatives"][0]["id"] == str(item.pk)


def test_search_limit_and_unknown_area(use):
    ItemFactory.create_batch(12)
    assert len(use("search_catalog", limit=500)["results"]) == 10
    assert "error" in use("search_catalog", service_area="Atlantis")


def test_details(use):
    item = ItemFactory(min_quantity=5)
    result = use("get_item_details", item_id=str(item.pk))
    assert (result["min_quantity"], result["vendor"]) == (5, item.vendor.business_name)
    package = PackageFactory(items=[item])
    assert use("get_item_details", package_id=str(package.pk))["contains"] == [item.name]
    for bad in ({}, {"item_id": "nope"}, {"item_id": str(uuid.uuid4())}):
        assert "error" in use("get_item_details", **bad)


def test_vendors_and_areas(use):
    area = ServiceAreaFactory(name="Ilala")
    vendor = VendorProfileFactory(service_areas=[area], offers_drinks=False)
    VendorProfileFactory(status="pending")
    result = use("list_vendors", service_area="Ilala", offers="food")["vendors"]
    assert [v["id"] for v in result] == [str(vendor.pk)]
    assert use("list_vendors", offers="drinks")["vendors"] == []
    assert use("list_service_areas")["areas"] == ["Ilala"]


# --- Identity ---------------------------------------------------------------


def test_register(use, conversation):
    result = use("register_client", full_name=" Asha ", preferred_language="sw")
    user = User.objects.get(pk=result["user_id"])
    assert (user.phone, user.full_name, user.role) == (PHONE, "Asha", "client")
    assert (user.created_via, user.preferred_language) == ("whatsapp", "sw")
    assert not user.has_usable_password()
    assert "user_id" in use("register_client", full_name="Again")
    assert User.objects.count() == 1


def test_register_needs_name_and_visible_phone(use, conversation):
    assert "error" in use("register_client", full_name="  ")
    conversation.wa_id, conversation.bsuid = None, "TZ.1"
    conversation.save()
    assert "phone" in use("register_client", full_name="Asha", phone=PHONE)["error"]
    assert not User.objects.exists()


BOOKING = ("create_event", "create_order", "quote_order", "start_payment", "cancel_order")


@pytest.mark.parametrize("name", [*BOOKING, "get_order_status"])
def test_unregistered_must_register(use, name):
    assert "register" in use(name)["error"]


@pytest.mark.parametrize("name", [*BOOKING, "get_order_status"])
@pytest.mark.parametrize(
    "factory", [VendorUserFactory, AdminFactory, lambda **k: ClientFactory(is_active=False, **k)]
)
def test_vendors_admins_and_inactive_cannot_book(use, name, factory):
    user = factory(phone=PHONE)
    if user.role == "vendor":
        order = OrderFactory(vendor=VendorProfileFactory(user=user))
    else:
        order = OrderFactory()
    result = use(name, order_reference=order.reference)
    assert set(result) == {"error"}


# --- Events -----------------------------------------------------------------


def event_args(**kwargs):
    return {
        "event_type": "wedding",
        "title": "Harusi",
        "starts_at": "2099-05-01T14:00:00",
        "venue": "Hall",
        "guest_count": 50,
    } | kwargs


def test_create_event_is_local_time_and_not_duplicated(use, me):
    first = use("create_event", **event_args())
    second = use("create_event", **event_args())
    assert first["event_id"] == second["event_id"]
    event = Event.objects.get()
    assert (event.client, event.starts_at.isoformat()) == (me, "2099-05-01T11:00:00+00:00")


@pytest.mark.parametrize(
    "bad", [{"starts_at": "2000-01-01T00:00"}, {"guest_count": 0}, {"event_type": "rave"}]
)
def test_create_event_validation(use, me, bad):
    assert "error" in use("create_event", **event_args(**bad))
    assert not Event.objects.exists()


# --- Orders -----------------------------------------------------------------


@pytest.fixture
def booking(me):
    item = ItemFactory(min_quantity=5)
    event = EventFactory(client=me)
    return {
        "event_id": str(event.pk),
        "vendor_id": str(item.vendor_id),
        "lines": [{"item_id": str(item.pk), "quantity": 10}],
    }


def test_quote_then_confirm(use, inbound, answered, booking):
    message = inbound()
    quote = use("quote_order", message, **booking)
    assert quote["total"] == "TZS 150,000"
    assert not Order.objects.exists()
    answered(message)
    result = use("create_order", **booking)
    order = Order.objects.get()
    assert (result["reference"], result["total"]) == (order.reference, "TZS 150,000")
    assert (order.channel, order.status) == ("whatsapp", "pending")


def test_order_without_quote(use, booking):
    assert "quote_order" in use("create_order", **booking)["error"]


def test_order_in_same_message_as_quote(use, inbound, booking):
    message = inbound()
    use("quote_order", message, **booking)
    assert "error" in use("create_order", message, **booking)
    assert not Order.objects.exists()


def test_order_sent_before_the_quote_was_shown(use, inbound, answered, booking):
    first, second = inbound(), inbound()
    use("quote_order", first, **booking)
    answered(first)  # later than `second`
    assert "error" in use("create_order", second, **booking)


def test_quote_whose_reply_was_a_fallback_does_not_count(use, inbound, answered, booking):
    message = inbound()
    use("quote_order", message, **booking)
    reply = answered(message)
    reply.payload = None
    reply.save()
    assert "error" in use("create_order", **booking)


def test_requoting_keeps_the_first_confirmation(use, inbound, answered, booking):
    message = inbound()
    use("quote_order", message, **booking)
    answered(message)
    later = inbound()
    use("quote_order", later, **booking)
    assert "reference" in use("create_order", later, **booking)


def test_changed_lines_or_price_need_a_new_quote(use, inbound, answered, booking):
    message = inbound()
    use("quote_order", message, **booking)
    answered(message)
    changed = booking | {"lines": [booking["lines"][0] | {"quantity": 11}]}
    assert "error" in use("create_order", **changed)
    vendor_item = booking["lines"][0]["item_id"]
    from apps.catalog.models import Item

    Item.objects.filter(pk=vendor_item).update(unit_price=Decimal("1"))
    assert "error" in use("create_order", **booking)
    assert not Order.objects.exists()


def test_rerun_does_not_book_twice(use, inbound, answered, booking):
    message = inbound()
    use("quote_order", message, **booking)
    answered(message)
    confirm = inbound()
    first = use("create_order", confirm, **booking)
    second = use("create_order", confirm, **booking)
    assert first["reference"] == second["reference"]
    assert Order.objects.count() == 1
    assert "error" in use("create_order", **booking)  # a new message needs a new quote


def test_same_rules_as_the_api(use, booking, me):
    line = booking["lines"][0]
    assert "minimum" in use("quote_order", **booking | {"lines": [line | {"quantity": 1}]})["error"]
    assert "error" in use("quote_order", **booking | {"event_id": str(EventFactory().pk)})
    assert "error" in use("quote_order", **booking | {"lines": "x"})
    soon = EventFactory(client=me, starts_at=timezone.now() + timedelta(hours=3))
    assert "notice" in use("quote_order", **booking | {"event_id": str(soon.pk)})["error"]


def test_alcohol_needs_age(use, me, inbound, answered):
    beer = ItemFactory(kind="drink", is_alcoholic=True)
    args = {
        "event_id": str(EventFactory(client=me).pk),
        "vendor_id": str(beer.vendor_id),
        "lines": [{"item_id": str(beer.pk), "quantity": 1}],
    }
    message = inbound()
    assert use("quote_order", message, **args)["age_confirmation_required"] is True
    answered(message)
    assert "18" in use("create_order", **args)["error"]
    assert "reference" in use("create_order", **args, age_confirmed=True)


def test_status_and_cancel_are_scoped(use, me):
    mine = OrderFactory(client=me)
    other = OrderFactory()
    assert [o["reference"] for o in use("get_order_status")["orders"]] == [mine.reference]
    for name in ("get_order_status", "cancel_order", "start_payment"):
        assert "error" in use(name, order_reference=other.reference, method="cash")
    result = use("cancel_order", order_reference=mine.reference.lower())
    assert result["status"] == "cancelled"
    other.refresh_from_db()
    assert other.status == "pending"


# --- Payment ----------------------------------------------------------------


def test_mobile_money_defaults_to_sender(use, me):
    order = OrderFactory(client=me, status="confirmed")
    result = use(
        "start_payment", order_reference=order.reference, method="mobile_money", provider="mpesa"
    )
    payment = order.payments.get()
    assert (payment.payer_phone, payment.method) == (PHONE, "online")
    assert result["payment_status"] == "pending"


def test_cash(use, me):
    order = OrderFactory(client=me, status="confirmed")
    result = use("start_payment", order_reference=order.reference, method="cash")
    assert result["order_status"] == "awaiting_cash"


@pytest.mark.parametrize(
    "args",
    [
        {"method": "mobile_money"},
        {"method": "mobile_money", "provider": "bank"},
        {"method": "online", "provider": "bank"},
        {"method": "mobile_money", "provider": "mpesa", "phone": "123"},
    ],
)
def test_payment_validation(use, me, args):
    order = OrderFactory(client=me, status="confirmed")
    assert "error" in use("start_payment", order_reference=order.reference, **args)
    assert not order.payments.exists()


def test_unconfirmed_order_and_gateway_down(use, me):
    pending = OrderFactory(client=me)
    assert "error" in use("start_payment", order_reference=pending.reference, method="cash")
    order = OrderFactory(client=me, status="confirmed")
    with patch("apps.payments.gateways.mock.MockGateway.checkout_mobile", side_effect=GatewayError):
        result = use(
            "start_payment", order_reference=order.reference, method="mobile_money", provider="tigo"
        )
    assert "error" in result
    order.refresh_from_db()
    assert order.status == "confirmed"


def test_unexpected_error_is_hidden(use):
    with patch.dict(tools.TOOLS, {"list_vendors": lambda ctx: 1 / 0}):
        assert use("list_vendors") == {"error": tools.GENERIC_ERROR}


def test_unexpected_arguments_are_reported(use):
    assert "error" in use("list_service_areas", bogus=1)
