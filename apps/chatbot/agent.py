"""Turns one inbound message into a reply, running tools as the model asks for them."""

import logging

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce

from . import grounding, prompts, tools
from .llm import get_llm
from .llm.base import LLMError, Turn
from .models import ChatMessage

logger = logging.getLogger(__name__)

Role, Status, Direction = ChatMessage.Role, ChatMessage.Status, ChatMessage.Direction

HISTORY = 20
MAX_ROUNDS = 5
CORRECTION = (
    "[Automatic check, not from the user] Your reply contained a price that no tool returned. "
    "Look it up with a tool, or reply without it."
)


def answer(conversation, user, inbound, *, keep_alive) -> ChatMessage:
    """Create the queued reply to `inbound`. Raises LLMError if there is no safe answer.

    `keep_alive` is called before each slow step.
    """
    llm = get_llm()
    turns = history(conversation, inbound)
    rounds = inbound.replies.filter(role=Role.TOOL).count()
    corrected = False
    while True:
        keep_alive()
        system = prompts.system_prompt(conversation, user)
        reply = llm.generate(system=system, turns=turns, tools=tools.DECLARATIONS)
        if reply.tool_calls:
            if rounds >= MAX_ROUNDS:
                raise LLMError("too many tool rounds")
            rounds += 1
            turns += _run_tools(conversation, inbound, reply)
            user = conversation.user  # may just have registered
            continue
        if grounding.prices(reply.text) <= grounding.known_prices(turns):
            return _save(
                inbound,
                role=Role.MODEL,
                text=reply.text,
                payload={"raw": reply.raw},
                status=Status.QUEUED,
            )
        logger.warning("Ungrounded price in reply to message %s", inbound.pk)
        if corrected:
            raise LLMError("ungrounded price")
        corrected = True
        turns += [Turn(Role.MODEL, reply.text, raw=reply.raw or {}), Turn(Role.USER, CORRECTION)]


def _run_tools(conversation, inbound, reply) -> list[Turn]:
    results = [
        {
            "id": call.id,
            "name": call.name,
            "response": tools.run(call.name, call.args, conversation, inbound),
        }
        for call in reply.tool_calls
    ]
    names = ",".join(call.name for call in reply.tool_calls)[:200]
    # Together, so stored history never has a call without its results.
    with transaction.atomic():
        _save(inbound, role=Role.MODEL, text=reply.text, payload={"raw": reply.raw})
        _save(inbound, role=Role.TOOL, tool_name=names, payload={"results": results})
    return [Turn(Role.MODEL, reply.text, raw=reply.raw), Turn(Role.TOOL, results=results)]


def _save(inbound, *, status=Status.PROCESSED, **fields) -> ChatMessage:
    return ChatMessage.objects.create(
        conversation_id=inbound.conversation_id,
        reply_to=inbound,
        direction=Direction.OUT,
        status=status,
        **fields,
    )


def history(conversation, inbound) -> list[Turn]:
    """The last messages up to `inbound`, each user message followed by its own replies."""
    text_only = Q(message_type="text") & (Q(reply_to=None) | Q(reply_to__message_type="text"))
    newest = (
        conversation.messages.filter(text_only)
        .exclude(status=Status.QUEUED)
        .annotate(anchor=Coalesce("reply_to_id", "id"))
        .filter(anchor__lte=inbound.pk)
        .order_by("-anchor", "-id")[:HISTORY]
    )
    messages = list(reversed(newest))
    # Starting at a user message keeps tool calls and their results together.
    while messages and messages[0].role != Role.USER:
        messages.pop(0)
    return [_turn(m) for m in messages]


def _turn(message) -> Turn:
    payload = message.payload or {}
    if message.role == Role.TOOL:
        return Turn(Role.TOOL, results=payload["results"])
    # Model text keeps a non-null raw, so only our own texts count as a price source.
    raw = (payload.get("raw") or {}) if message.payload is not None else None
    return Turn(message.role, message.text, raw=raw)
