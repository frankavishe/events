import json

import httpx
import pytest
import respx
from django.core.exceptions import ImproperlyConfigured

from apps.notifications.clients import (
    FakeMessagingClient,
    MessagingError,
    Recipient,
    WhatsAppCloudClient,
    get_messaging_client,
)

URL = "https://graph.facebook.com/v26.0/PNID/messages"
PHONE = Recipient(phone="+255712345678")


@pytest.fixture(autouse=True)
def whatsapp(settings):
    settings.MESSAGING_PROVIDER = "whatsapp"
    settings.WHATSAPP_ACCESS_TOKEN = "tok-secret"
    settings.WHATSAPP_PHONE_NUMBER_ID = "PNID"
    settings.WHATSAPP_GRAPH_VERSION = "v26.0"


def ok():
    return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})


def body(route, index=0):
    return json.loads(route.calls[index].request.content)


@respx.mock
def test_text():
    route = respx.post(URL).mock(return_value=ok())
    assert get_messaging_client().send_text(PHONE, "Habari") == "wamid.X"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok-secret"
    assert body(route) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "255712345678",
        "type": "text",
        "text": {"preview_url": False, "body": "Habari"},
    }


@respx.mock
def test_bsuid_uses_recipient():
    route = respx.post(URL).mock(return_value=ok())
    get_messaging_client().send_text(Recipient(bsuid="TZ.1"), "Hi")
    assert body(route)["recipient"] == "TZ.1"
    assert "to" not in body(route)


@respx.mock
def test_template():
    route = respx.post(URL).mock(return_value=ok())
    get_messaging_client().send_template(PHONE, "new_order", "sw", ["EVT-1", "a\n\tb    c", ""])
    assert body(route)["template"] == {
        "name": "new_order",
        "language": {"code": "sw"},
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "EVT-1"},
                    {"type": "text", "text": "a b c"},
                    {"type": "text", "text": "-"},
                ],
            }
        ],
    }


@respx.mock
def test_long_text_is_split_without_loss():
    route = respx.post(URL).mock(return_value=ok())
    text = "word " * 2000
    get_messaging_client().send_text(PHONE, text)
    parts = [body(route, i)["text"]["body"] for i in range(route.call_count)]
    assert all(len(p) <= 4096 for p in parts)
    assert " ".join(parts).split() == text.split()


@respx.mock
@pytest.mark.parametrize(
    ("outcome", "transient"),
    [
        (httpx.ConnectError("x"), True),
        (httpx.ReadTimeout("x"), True),
        (429, True),
        (503, True),
        (400, False),
        (401, False),
    ],
)
def test_errors(outcome, transient, caplog):
    route = respx.post(URL)
    if isinstance(outcome, Exception):
        route.mock(side_effect=outcome)
    else:
        route.mock(return_value=httpx.Response(outcome, text="private body tok-secret"))
    with pytest.raises(MessagingError) as exc:
        get_messaging_client().send_text(PHONE, "private body")
    assert exc.value.transient is transient
    for secret in ("tok-secret", "private body"):
        assert secret not in caplog.text + str(exc.value)


@respx.mock
def test_accepted_without_readable_body_is_not_resent():
    respx.post(URL).mock(return_value=httpx.Response(200, text="?"))
    assert get_messaging_client().send_text(PHONE, "x") is None


def test_factory(settings):
    assert isinstance(get_messaging_client(), WhatsAppCloudClient)
    settings.WHATSAPP_ACCESS_TOKEN = ""
    with pytest.raises(ImproperlyConfigured):
        get_messaging_client()
    settings.MESSAGING_PROVIDER = "fake"
    assert isinstance(get_messaging_client(), FakeMessagingClient)
    settings.MESSAGING_PROVIDER = "x"
    with pytest.raises(ImproperlyConfigured):
        get_messaging_client()
