import hashlib
import hmac
import json
from pathlib import Path

import pytest

from apps.chatbot.llm.fake import FakeLLM
from apps.chatbot.models import ChatMessage, Conversation
from apps.notifications.clients import FakeMessagingClient

URL = "/api/v1/webhooks/whatsapp/"
PHONE = "255712345678"


@pytest.fixture(autouse=True)
def fakes(settings):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    settings.WHATSAPP_VERIFY_TOKEN = "verify-me"
    settings.WHATSAPP_PHONE_NUMBER_ID = "PNID"
    FakeMessagingClient.reset()
    FakeLLM.reset()
    yield
    FakeMessagingClient.reset()
    FakeLLM.reset()


@pytest.fixture
def outbox():
    return FakeMessagingClient.outbox


@pytest.fixture
def payload():
    """Build a webhook payload. `message` overrides message keys; None removes a key."""
    base = (Path(__file__).parent / "fixtures" / "text_message.json").read_text()

    def build(text=None, *, wamid="wamid.1", **message):
        data = json.loads(base)
        value = data["entry"][0]["changes"][0]["value"]
        target = value["messages"][0]
        target["id"] = wamid
        if text is not None:
            target["text"]["body"] = text
        for key, new in message.items():
            if new is None:
                target.pop(key, None)
            else:
                target[key] = new
        if message.get("from", "") is None:
            value["contacts"][0].pop("wa_id")
        return data

    return build


@pytest.fixture
def post(client):
    def send(data, signature=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        digest = hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        return client.post(
            URL,
            body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature or f"sha256={digest}"},
        )

    return send


@pytest.fixture
def chat(post, payload, outbox, django_capture_on_commit_callbacks):
    """Send a text as the client and return the assistant's reply."""
    counter = iter(range(1000))

    def send(text):
        before = len(outbox)
        with django_capture_on_commit_callbacks(execute=True):
            assert post(payload(text, wamid=f"chat.{next(counter)}")).status_code == 200
        return "\n".join(m["text"] for m in outbox[before:])

    return send


@pytest.fixture
def conversation(db):
    return Conversation.objects.create(wa_id=PHONE, language="en")


@pytest.fixture
def inbound(conversation):
    def make(text="hello", **kwargs):
        return ChatMessage.objects.create(
            conversation=conversation,
            direction="in",
            role="user",
            text=text,
            status="received",
            **kwargs,
        )

    return make
