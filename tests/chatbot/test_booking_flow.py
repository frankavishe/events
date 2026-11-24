import pytest

from apps.accounts.models import User
from apps.chatbot.llm.base import LLMReply, ToolCall
from apps.chatbot.llm.fake import FakeLLM
from apps.events.models import Event
from apps.orders import services as orders
from apps.orders.models import Order
from tests.factories import ItemFactory

pytestmark = pytest.mark.django_db


def call(name, **args):
    return LLMReply(tool_calls=[ToolCall(name=name, args=args, id="1")])


def last_result(index=-1):
    return FakeLLM.calls[index]["turns"][-1].results[0]["response"]


def test_unknown_number_books_and_pays_cash(chat, outbox, django_capture_on_commit_callbacks):
    item = ItemFactory(min_quantity=5)

    FakeLLM.script(LLMReply(text="Karibu! Jina lako nani?"))
    assert "Jina" in chat("Nataka chakula cha harusi")

    FakeLLM.script(
        call("register_client", full_name="Asha Juma", preferred_language="sw"),
        LLMReply(text="Asante Asha. Tarehe na ukumbi?"),
    )
    chat("Asha Juma")
    user = User.objects.get(phone="+255712345678")

    FakeLLM.script(
        call(
            "create_event",
            event_type="wedding",
            title="Harusi",
            starts_at="2099-05-01T14:00",
            venue="Mlimani",
            guest_count=100,
        ),
        LLMReply(text="Sawa. Chakula gani?"),
    )
    chat("1 Mei 2099 saa nane, Mlimani, watu 100")
    event = Event.objects.get(client=user)

    booking = {
        "event_id": str(event.pk),
        "vendor_id": str(item.vendor_id),
        "lines": [{"item_id": str(item.pk), "quantity": 100}],
    }
    FakeLLM.script(
        call("quote_order", **booking), LLMReply(text="Jumla ni TZS 1,500,000. Unathibitisha?")
    )
    assert "TZS 1,500,000" in chat("Sahani 100")

    FakeLLM.script(call("create_order", **booking), LLMReply(text="Imewekwa."))
    assert chat("Ndiyo").startswith("Imewekwa.") or "Imewekwa." in outbox[-1]["text"]
    order = Order.objects.get(client=user)
    assert last_result()["reference"] == order.reference
    # The vendor was notified.
    assert any(m["phone"] == item.vendor.contact_phone.lstrip("+") for m in outbox)

    with django_capture_on_commit_callbacks(execute=True):
        orders.transition(order, "confirmed", item.vendor.user)
    assert order.reference in outbox[-1]["text"]
    assert outbox[-1]["phone"] == "255712345678"

    FakeLLM.script(
        call("start_payment", order_reference=order.reference, method="cash"),
        LLMReply(text="Sawa, utalipa taslimu."),
    )
    chat("Nitalipa cash")
    order.refresh_from_db()
    assert (order.status, order.channel) == ("awaiting_cash", "whatsapp")
