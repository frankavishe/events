"""Receiving and answering WhatsApp messages."""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.common.logs import log_event
from apps.notifications.clients import MessagingError, Recipient, get_messaging_client

from . import agent, prompts
from .llm.base import LLMError
from .models import ChatMessage, Conversation

logger = logging.getLogger(__name__)

Status, Role, Direction = ChatMessage.Status, ChatMessage.Role, ChatMessage.Direction

LEASE = timedelta(minutes=5)
STUCK_AFTER = timedelta(minutes=1)
MAX_ATTEMPTS = 3
MAX_TEXT = 4096


# --- Receiving -------------------------------------------------------------


@transaction.atomic
def receive(message: dict) -> ChatMessage | None:
    """Store one inbound message; None if it is a duplicate. Raises ValueError if unusable."""
    wamid, wa_id, bsuid = (message.get(k) for k in ("id", "from", "from_user_id"))
    kind = message.get("type")
    for value, limit in ((wamid, 255), (kind, 30)):
        if not isinstance(value, str) or not 0 < len(value) <= limit:
            raise ValueError("missing id or type")
    for value, limit in ((wa_id, 32), (bsuid, 160)):
        if value is not None and not (isinstance(value, str) and len(value) <= limit):
            raise ValueError("bad sender")
    if not wa_id and not bsuid:
        raise ValueError("no sender")
    text = ""
    if kind == "text":
        text = message["text"]["body"] if isinstance(message.get("text"), dict) else None
        if not isinstance(text, str):
            raise ValueError("no text")
        text = text.replace("\x00", "")[:MAX_TEXT]  # PostgreSQL cannot store NUL

    conversation = _conversation(wa_id or None, bsuid or None)
    stored, created = ChatMessage.objects.get_or_create(
        wa_message_id=wamid,
        defaults={
            "conversation": conversation,
            "direction": Direction.IN,
            "role": Role.USER,
            "message_type": kind,
            "text": text,
        },
    )
    if not created:
        return None
    Conversation.objects.filter(pk=conversation.pk).update(last_inbound_at=timezone.now())
    return stored


def _conversation(wa_id, bsuid) -> Conversation:
    by_phone = Conversation.objects.filter(wa_id=wa_id).first() if wa_id else None
    by_bsuid = Conversation.objects.filter(bsuid=bsuid).first() if bsuid else None
    if by_phone:
        if bsuid and not by_phone.bsuid and not by_bsuid:
            by_phone.bsuid = bsuid
            by_phone.save(update_fields=["bsuid", "updated_at"])
        return by_phone
    if by_bsuid and (not wa_id or not by_bsuid.wa_id):
        if wa_id:
            by_bsuid.wa_id = wa_id
            by_bsuid.save(update_fields=["wa_id", "updated_at"])
        return by_bsuid
    if by_bsuid:  # same person, new number: the id stays with the old conversation
        bsuid = None
    key = {"wa_id": wa_id} if wa_id else {"bsuid": bsuid}
    return Conversation.objects.get_or_create(**key, defaults={"bsuid": bsuid, "wa_id": wa_id})[0]


def record_delivery(wa_message_id, status) -> None:
    ChatMessage.objects.filter(wa_message_id=wa_message_id, direction=Direction.OUT).update(
        delivery_status=status[:20]
    )


# --- Answering -------------------------------------------------------------


def process_conversation(conversation_id) -> None:
    """Answer waiting messages in order. Does nothing if another worker is doing so."""
    while _waiting(conversation_id).exists():
        conversation = _claim(conversation_id)
        if conversation is None:
            return
        try:
            healthy = _answer_all(conversation)
        finally:
            _release(conversation)
        if not healthy:
            return  # the sweep tries again later
        # Loop: a message may have arrived between the last check and the release.


def stuck_conversations() -> list:
    return list(
        ChatMessage.objects.filter(
            status=Status.RECEIVED,
            direction=Direction.IN,
            created_at__lte=timezone.now() - STUCK_AFTER,
        )
        .order_by()
        .values_list("conversation_id", flat=True)
        .distinct()
    )


def _waiting(conversation_id):
    return ChatMessage.objects.filter(
        conversation_id=conversation_id, direction=Direction.IN, status=Status.RECEIVED
    ).order_by("id")


def _claim(conversation_id) -> Conversation | None:
    """Take the lease with one conditional update, so no row stays locked while answering."""
    now = timezone.now()
    free = Q(processing_until=None) | Q(processing_until__lt=now)
    claimed = Conversation.objects.filter(free, pk=conversation_id).update(
        processing_until=now + LEASE
    )
    return Conversation.objects.select_related("user").get(pk=conversation_id) if claimed else None


def _renew(conversation):
    until = timezone.now() + LEASE
    kept = Conversation.objects.filter(
        pk=conversation.pk, processing_until=conversation.processing_until
    ).update(processing_until=until)
    if not kept:
        raise LeaseLost
    conversation.processing_until = until


def _release(conversation):
    Conversation.objects.filter(
        pk=conversation.pk, processing_until=conversation.processing_until
    ).update(processing_until=None)


class LeaseLost(Exception):
    """Another worker took over after this one was too slow."""


def _answer_all(conversation) -> bool:
    while message := _waiting(conversation.pk).first():
        try:
            _renew(conversation)
            if not _answer(conversation, message):
                return False
        except LeaseLost:
            logger.warning("Lost the lease on conversation %s", conversation.pk)
            return False
    return True


def _answer(conversation, message) -> bool:
    """Answer one message. False if sending should be tried again later."""
    reply = message.replies.filter(status=Status.QUEUED).first()  # written but not sent
    if reply is None:
        reply = _write_reply(conversation, message)
    try:
        wamid = get_messaging_client().send_text(
            Recipient(
                phone=f"+{conversation.wa_id}" if conversation.wa_id else "",
                bsuid=conversation.bsuid or "",
            ),
            reply.text,
        )
    except MessagingError as exc:
        message.attempts += 1
        if exc.transient and message.attempts < MAX_ATTEMPTS:
            message.save(update_fields=["attempts", "updated_at"])
            return False
        logger.error("Reply to message %s could not be sent", message.pk)
        _set_status(reply, Status.FAILED)
        _set_status(message, Status.FAILED)
        return True
    reply.wa_message_id = wamid
    _set_status(reply, Status.SENT)
    # A fallback was sent if there is no model content: keep the message marked as failed.
    failed = message.message_type == "text" and reply.payload is None
    _set_status(message, Status.FAILED if failed else Status.PROCESSED)
    log_event(logger, "chat.failed" if failed else "chat.processed", message=message.pk)
    return True


def _write_reply(conversation, message) -> ChatMessage:
    if message.message_type != "text":
        return _fixed_reply(message, prompts.text("text_only", conversation.language))
    language = prompts.detect_language(message.text, conversation.language)
    if language != conversation.language:
        conversation.language = language
        conversation.save(update_fields=["language", "updated_at"])
    try:
        return agent.answer(
            conversation,
            identify(conversation),
            message,
            keep_alive=lambda: _renew(conversation),
        )
    except LeaseLost:
        raise
    except LLMError as exc:
        logger.warning("No answer to message %s: %s", message.pk, exc)
    except Exception:
        logger.exception("Answering message %s failed", message.pk)
    return _fixed_reply(message, prompts.text("fallback", language))


def _fixed_reply(message, text) -> ChatMessage:
    return ChatMessage.objects.create(
        conversation_id=message.conversation_id,
        reply_to=message,
        direction=Direction.OUT,
        role=Role.MODEL,
        text=text,
        status=Status.QUEUED,
    )


def identify(conversation) -> User | None:
    """The account with the sender's phone, which Meta vouches for."""
    if conversation.user is None and conversation.phone:
        conversation.user = User.objects.filter(phone=conversation.phone).first()
        if conversation.user:
            conversation.save(update_fields=["user", "updated_at"])
    return conversation.user


def _set_status(message, status):
    message.status = status
    message.save(update_fields=["status", "wa_message_id", "updated_at"])
