import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.chatbot import services, tasks
from apps.chatbot.llm.base import LLMReply
from apps.chatbot.llm.fake import FakeLLM
from apps.chatbot.models import ChatMessage, Conversation
from apps.notifications.clients import FakeMessagingClient, MessagingError

from .conftest import URL

pytestmark = pytest.mark.django_db


def verify(client, token="verify-me", mode="subscribe"):  # noqa: S107
    params = {"hub.mode": mode, "hub.verify_token": token, "hub.challenge": "12345"}
    return client.get(URL, params)


def test_verify(client):
    response = verify(client)
    assert (response.status_code, response.content) == (200, b"12345")


def test_verify_rejects(client, settings):
    assert verify(client, token="no").status_code == 403
    assert verify(client, mode="x").status_code == 403
    assert client.get(URL).status_code == 403
    settings.WHATSAPP_VERIFY_TOKEN = ""
    assert verify(client, token="").status_code == 403


@pytest.mark.parametrize("signature", ["sha256=00", "nonsense", "sha256=é"])
def test_bad_signature(post, payload, signature):
    assert post(payload(), signature=signature).status_code == 403
    assert not ChatMessage.objects.exists()


def test_missing_signature_and_unset_secret(client, post, payload, settings):
    assert client.post(URL, {}, content_type="application/json").status_code == 403
    settings.WHATSAPP_APP_SECRET = ""
    assert post(payload()).status_code == 403


def test_stores_and_enqueues(post, payload, django_capture_on_commit_callbacks):
    with (
        patch.object(tasks.process_message, "delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        assert post(payload()).status_code == 200
    message = ChatMessage.objects.get()
    delay.assert_called_once_with(message.pk)
    assert (message.text, message.status) == ("Bei ya soda ni kiasi gani?", "received")
    conversation = message.conversation
    assert (conversation.wa_id, conversation.bsuid) == ("255712345678", "TZ.1349")
    assert conversation.last_inbound_at is not None


def test_duplicate_wamid(post, payload, django_capture_on_commit_callbacks):
    with (
        patch.object(tasks.process_message, "delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        post(payload())
        post(payload())
    assert ChatMessage.objects.count() == 1
    assert delay.call_count == 1


def test_broker_down_still_200_and_sweep_recovers(
    post, payload, outbox, django_capture_on_commit_callbacks
):
    with (
        patch.object(tasks.process_message, "delay", side_effect=OSError("broker")),
        django_capture_on_commit_callbacks(execute=True),
    ):
        assert post(payload()).status_code == 200
    ChatMessage.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    FakeLLM.script(LLMReply(text="Habari"))
    tasks.resume_stuck_messages()
    assert [m["text"] for m in outbox] == ["Habari"]


def test_hidden_phone_uses_bsuid(post, payload, outbox, django_capture_on_commit_callbacks):
    FakeLLM.script(LLMReply(text="Hi"))
    with django_capture_on_commit_callbacks(execute=True):
        post(payload("hello", **{"from": None}))
    conversation = Conversation.objects.get()
    assert (conversation.wa_id, conversation.phone) == (None, None)
    assert (outbox[0]["phone"], outbox[0]["bsuid"]) == ("", "TZ.1349")


def test_phone_appearing_later_keeps_conversation(post, payload):
    post(payload(wamid="a", **{"from": None}))
    post(payload(wamid="b"))
    assert Conversation.objects.get().wa_id == "255712345678"


def test_bsuid_never_overrides_another_phone(post, payload):
    post(payload(wamid="a"))
    post(payload(wamid="b", **{"from": "255799999999"}))
    assert Conversation.objects.count() == 2


def test_non_text_gets_canned_reply(post, payload, outbox, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        post(payload(type="image", text=None, image={"id": "1"}))
    assert "text" in outbox[0]["text"]
    assert FakeLLM.calls == []


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"entry": 3}', b'{"entry": [{"changes": [{"value": null}]}]}'],
)
def test_malformed_is_acknowledged(post, body):
    assert post(body).status_code == 200


def test_malformed_message_does_not_hide_good_one(post, payload):
    data = payload()
    data["entry"][0]["changes"][0]["value"]["messages"].insert(0, {"id": "x"})
    post(data)
    assert ChatMessage.objects.count() == 1


def test_other_phone_number_ignored(post, payload, settings):
    settings.WHATSAPP_PHONE_NUMBER_ID = "OTHER"
    assert post(payload()).status_code == 200
    assert not ChatMessage.objects.exists()


@pytest.mark.parametrize("number", ["PNID", None])
def test_other_fields_ignored(post, payload, caplog, number):
    data = payload()
    change = data["entry"][0]["changes"][0]
    change["field"] = "message_template_status_update"
    if number is None:
        del change["value"]["metadata"]
    with caplog.at_level(logging.WARNING):
        assert post(data).status_code == 200
    assert not ChatMessage.objects.exists()
    assert "other phone number" not in caplog.text


def test_largest_payload_is_accepted(post, payload):
    data = payload()
    data["padding"] = "x" * (3 * 1024 * 1024 - 2048)
    assert post(data).status_code == 200
    assert ChatMessage.objects.count() == 1


def stamp(when):
    return str(int(when.timestamp()))


def test_late_delivery_does_not_reopen_the_window(post, payload):
    sent = timezone.now().replace(microsecond=0) - timedelta(days=2)
    post(payload(timestamp=stamp(sent)))
    assert Conversation.objects.get().last_inbound_at == sent


def test_window_never_moves_back(post, payload):
    now = timezone.now().replace(microsecond=0)
    post(payload(wamid="new", timestamp=stamp(now - timedelta(hours=1))))
    post(payload(wamid="old", timestamp=stamp(now - timedelta(days=2))))
    assert ChatMessage.objects.count() == 2
    assert Conversation.objects.get().last_inbound_at == now - timedelta(hours=1)


@pytest.mark.parametrize(
    "timestamp",
    [None, "abc", "", 5, [], "9" * 30, "9" * 5000, "²", stamp(datetime(2999, 1, 1, tzinfo=UTC))],
)
def test_unusable_or_future_timestamp_counts_as_now(post, payload, timestamp):
    before = timezone.now()
    assert post(payload(timestamp=timestamp)).status_code == 200
    assert before <= Conversation.objects.get().last_inbound_at <= timezone.now()


def test_nul_bytes_are_removed(post, payload):
    post(payload("a\x00b"))
    assert ChatMessage.objects.get().text == "ab"


def test_delivery_status_stored(post, payload, conversation):
    sent = ChatMessage.objects.create(
        conversation=conversation, direction="out", role="model", wa_message_id="out.1"
    )
    data = payload()
    value = data["entry"][0]["changes"][0]["value"]
    del value["messages"]
    value["statuses"] = [{"id": "out.1", "status": "delivered"}]
    assert post(data).status_code == 200
    sent.refresh_from_db()
    assert sent.delivery_status == "delivered"


def test_busy_conversation_is_left_to_its_worker(conversation, inbound, outbox):
    inbound()
    conversation.processing_until = timezone.now() + timedelta(minutes=1)
    conversation.save()
    services.process_conversation(conversation.pk)
    assert outbox == []


def test_message_arriving_mid_turn_is_answered_in_order(conversation, inbound, outbox):
    inbound("first")

    def during(**kwargs):
        inbound("second")
        # A second worker cannot interleave.
        services.process_conversation(conversation.pk)
        return LLMReply(text="one")

    FakeLLM.script(during, LLMReply(text="two"))
    services.process_conversation(conversation.pk)
    assert [m["text"] for m in outbox] == ["one", "two"]
    assert [t.text for t in FakeLLM.calls[1]["turns"]] == ["first", "one", "second"]


def test_failed_send_is_retried_without_a_new_llm_call(conversation, inbound, outbox):
    message = inbound()
    FakeLLM.script(LLMReply(text="Hi"))
    FakeMessagingClient.fail_with = MessagingError(transient=True)
    services.process_conversation(conversation.pk)
    message.refresh_from_db()
    assert message.status == "received"
    FakeMessagingClient.fail_with = None
    services.process_conversation(conversation.pk)
    message.refresh_from_db()
    assert message.status == "processed"
    assert len(outbox) == 1
    assert len(FakeLLM.calls) == 1


def test_gives_up_after_repeated_send_failures(conversation, inbound):
    message = inbound()
    FakeLLM.script(LLMReply(text="Hi"))
    FakeMessagingClient.fail_with = MessagingError(transient=True)
    for _ in range(services.MAX_ATTEMPTS):
        services.process_conversation(conversation.pk)
    message.refresh_from_db()
    assert message.status == "failed"


def failed(payload, errors, wamid="out.1"):
    data = payload()
    value = data["entry"][0]["changes"][0]["value"]
    del value["messages"]
    value["statuses"] = [
        {"id": wamid, "status": "failed", "recipient_id": "255712345678", "errors": errors}
    ]
    return data


@pytest.mark.parametrize("wamid", ["out.1", "sent-from-the-dashboard"])
def test_failed_delivery_logs_the_code_only(post, payload, conversation, caplog, wamid):
    sent = ChatMessage.objects.create(
        conversation=conversation, direction="out", role="model", wa_message_id="out.1"
    )
    errors = [{"code": 131042, "title": "secret title", "error_data": {"details": "secret"}}]
    assert post(failed(payload, errors, wamid)).status_code == 200
    sent.refresh_from_db()
    assert sent.delivery_status == ("failed" if wamid == "out.1" else "")
    assert "WhatsApp delivery failed (code 131042)" in caplog.text
    assert "secret" not in caplog.text
    assert "255712345678" not in caplog.text


@pytest.mark.parametrize("errors", [None, [], "secret", ["secret"], [{}], [{"code": "secret"}]])
def test_failed_delivery_with_unusable_errors(post, payload, caplog, errors):
    assert post(failed(payload, errors)).status_code == 200
    assert "WhatsApp delivery failed (code None)" in caplog.text
    assert "secret" not in caplog.text
