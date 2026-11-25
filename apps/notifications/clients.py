"""Outgoing WhatsApp messages. Tokens and message texts are never logged or put in errors."""

import logging
import sys
from dataclasses import dataclass
from itertools import count
from typing import ClassVar, Protocol

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.common.exceptions import GatewayError

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15
MAX_TEXT = 4096


class MessagingError(GatewayError):
    """`transient` means that trying again later may work."""

    def __init__(self, *, transient: bool):
        super().__init__("The message could not be sent.")
        self.transient = transient


@dataclass(frozen=True)
class Recipient:
    """`phone` is E.164. `bsuid` is used only when there is no phone."""

    phone: str = ""
    bsuid: str = ""

    @property
    def wa_id(self) -> str:
        return self.phone.removeprefix("+")


class MessagingClient(Protocol):
    """All methods return the provider's message id, if known, or raise MessagingError."""

    def send_text(self, recipient: Recipient, text: str) -> str | None: ...

    def send_template(
        self, recipient: Recipient, name: str, language: str, params: list[str]
    ) -> str | None: ...

    def send_auth_code(
        self, recipient: Recipient, name: str, language: str, code: str
    ) -> str | None: ...


class WhatsAppCloudClient:
    def __init__(self):
        for name in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"):
            if not getattr(settings, name):
                raise ImproperlyConfigured(f"WhatsApp needs {name}")
        self.url = (
            f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}"
            f"/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )

    def send_text(self, recipient, text):
        message_id = None
        for part in split_text(text):
            message_id = self._send(
                recipient, {"type": "text", "text": {"preview_url": False, "body": part}}
            )
        return message_id

    def send_template(self, recipient, name, language, params):
        # Meta rejects empty parameters, line breaks, tabs and runs of spaces.
        parameters = [{"type": "text", "text": " ".join(p.split()) or "-"} for p in params]
        template = {
            "name": name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": parameters}],
        }
        return self._send(recipient, {"type": "template", "template": template})

    def send_auth_code(self, recipient, name, language, code):
        # Meta wants the code twice: in the text and for the "copy code" button, which it stores
        # as a URL button. Needs a phone; a bsuid is refused.
        parameters = [{"type": "text", "text": code}]
        template = {
            "name": name,
            "language": {"code": language},
            "components": [
                {"type": "body", "parameters": parameters},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": parameters},
            ],
        }
        return self._send(recipient, {"type": "template", "template": template})

    def _send(self, recipient, content):
        address = {"to": recipient.wa_id} if recipient.phone else {"recipient": recipient.bsuid}
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            **address,
            **content,
        }
        headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
        try:
            response = httpx.post(self.url, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            logger.warning("WhatsApp send failed: %s", type(exc).__name__)
            raise MessagingError(transient=True) from None
        if not response.is_success:
            logger.warning("WhatsApp send returned HTTP %s", response.status_code)
            raise MessagingError(
                transient=response.status_code == 429 or response.status_code >= 500
            )
        try:
            return response.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            logger.warning("WhatsApp accepted a message without returning its id")
            return None


class FakeMessagingClient:
    """Records messages in `outbox`. Set `fail_with` to make sending fail."""

    outbox: ClassVar[list[dict]] = []
    fail_with: ClassVar[Exception | None] = None
    _ids: ClassVar = count(1)

    @classmethod
    def reset(cls):
        cls.outbox.clear()
        cls.fail_with = None

    def send_text(self, recipient, text):
        return self._record(recipient, text=text, template=None)

    def send_template(self, recipient, name, language, params):
        return self._record(recipient, text="", template=name, language=language, params=params)

    def send_auth_code(self, recipient, name, language, code):
        message_id = self.send_template(recipient, name, language, [code])
        if settings.DEBUG:  # so that it can be used in local development
            print(f"[fake WhatsApp] password code: {code}", file=sys.stderr)
        return message_id

    def _record(self, recipient, **message):
        if self.fail_with:
            raise self.fail_with
        self.outbox.append({"phone": recipient.wa_id, "bsuid": recipient.bsuid, **message})
        return f"fake.{next(self._ids)}"


def get_messaging_client() -> MessagingClient:
    """The client selected by `settings.MESSAGING_PROVIDER`."""
    if settings.MESSAGING_PROVIDER == "fake":
        return FakeMessagingClient()
    if settings.MESSAGING_PROVIDER == "whatsapp":
        return WhatsAppCloudClient()
    raise ImproperlyConfigured(f"Unknown MESSAGING_PROVIDER: {settings.MESSAGING_PROVIDER!r}")


def split_text(text: str) -> list[str]:
    """Split at line breaks or spaces where possible."""
    parts = []
    while len(text) > MAX_TEXT:
        cut = text.rfind("\n", 1, MAX_TEXT)
        if cut == -1:
            cut = text.rfind(" ", 1, MAX_TEXT)
        if cut == -1:
            cut = MAX_TEXT
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return [*parts, text] if text else parts
