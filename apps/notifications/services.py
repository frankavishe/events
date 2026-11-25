"""What each notification says and how it is sent."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.chatbot.models import ChatMessage, Conversation

from .clients import Recipient, get_messaging_client

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)

NEW_ORDER = {
    "en": "New order {} for {}. Total: {}. Please confirm or decline it within 24 hours.",
    "sw": "Oda mpya {} ya tarehe {}. Jumla: {}. Tafadhali ithibitishe au ikatae ndani ya saa 24.",
}
ORDER_STATUS = {
    "en": "Your order {} is now {}. Total: {}.",
    "sw": "Oda yako {} sasa {}. Jumla: {}.",
}
PAYMENT_FAILED = {
    "en": "The payment for order {} ({}) did not go through. You can try again or pay cash.",
    "sw": "Malipo ya oda {} ({}) hayakufanikiwa. Unaweza kujaribu tena au kulipa taslimu.",
}
STATUS_NAMES = {
    "en": {
        "confirmed": "confirmed",
        "declined": "declined",
        "expired": "expired (no reply from the vendor)",
        "cancelled": "cancelled",
        "awaiting_cash": "awaiting cash payment",
        "paid": "paid",
        "fulfilled": "delivered",
        "completed": "completed",
        "refunded": "refunded",
    },
    "sw": {
        "confirmed": "imethibitishwa",
        "declined": "imekataliwa",
        "expired": "imeisha muda (muuzaji hakujibu)",
        "cancelled": "imeghairiwa",
        "awaiting_cash": "inasubiri malipo ya taslimu",
        "paid": "imelipwa",
        "fulfilled": "imetolewa",
        "completed": "imekamilika",
        "refunded": "imerudishiwa pesa",
    },
}


def send(*, phone, language, texts, params, template, extra="") -> None:
    """Free text inside the 24 h window, otherwise the approved template."""
    recipient = Recipient(phone=phone)
    conversation = Conversation.objects.filter(wa_id=recipient.wa_id).first()
    text = " ".join(filter(None, [texts[language].format(*params), extra]))
    client = get_messaging_client()
    if _window_open(conversation):
        message_id = client.send_text(recipient, text)
    elif template:
        message_id = client.send_template(recipient, template, language, params)
    else:
        logger.warning("Notification skipped: outside the 24 h window and no template set")
        return
    if conversation:  # so the assistant knows what the user was told
        ChatMessage.objects.create(
            conversation=conversation,
            direction=ChatMessage.Direction.OUT,
            role=ChatMessage.Role.MODEL,
            wa_message_id=message_id,
            text=text,
            status=ChatMessage.Status.SENT,
        )


def send_auth_code(*, phone, language, code) -> None:
    """Always the template, and never kept in the chat history, which the LLM reads."""
    get_messaging_client().send_auth_code(
        Recipient(phone=phone), settings.WHATSAPP_TEMPLATE_AUTH_CODE, language, code
    )


def _window_open(conversation) -> bool:
    return bool(
        conversation
        and conversation.last_inbound_at
        and conversation.last_inbound_at > timezone.now() - WINDOW
    )
