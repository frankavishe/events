"""Google Gemini with manual function calling.

Gemini 3 rejects history whose function calls lost their thought signature or their order, so
model messages are stored and replayed whole. Temperature is left at the model's default.
"""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google import genai
from google.genai import types

from .base import LLMError, LLMReply, ToolCall

logger = logging.getLogger(__name__)

TIMEOUT_MS = 20_000
ATTEMPTS = 2


class GeminiClient:
    def __init__(self):
        if not settings.GEMINI_API_KEY:
            raise ImproperlyConfigured("Gemini needs GEMINI_API_KEY")
        self._client = genai.Client(  # kept: closing it closes the connection
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(
                    attempts=ATTEMPTS, initial_delay=1, max_delay=3
                ),
            ),
        )
        self.models = self._client.models
        self.model = settings.GEMINI_MODEL

    def generate(self, *, system, turns, tools):
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[_declaration(t) for t in tools])]
            if tools
            else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self.models.generate_content(
                model=self.model, contents=[_content(t) for t in turns], config=config
            )
        except Exception as exc:
            # The message may quote the conversation, so only the kind of error is kept.
            kind = f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()
            logger.warning("Gemini request failed: %s", kind)
            raise LLMError(kind) from None
        return _reply(response)


def _declaration(tool):
    return types.FunctionDeclaration(
        name=tool["name"],
        description=tool["description"],
        parameters_json_schema=tool["parameters"],
    )


def _content(turn):
    if turn.role == "tool":
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=r["id"], name=r["name"], response=r["response"]
                )
            )
            for r in turn.results
        ]
        return types.Content(role="user", parts=parts)
    if turn.raw:
        return types.Content.model_validate(turn.raw)
    return types.Content(role=turn.role, parts=[types.Part(text=turn.text)])


def _reply(response):
    content = response.candidates[0].content if response.candidates else None
    parts = (content.parts if content else None) or []
    text = "".join(p.text for p in parts if p.text and not p.thought).strip()
    calls = [
        ToolCall(name=c.name, args=dict(c.args or {}), id=c.id)
        for c in (p.function_call for p in parts)
        if c
    ]
    if not text and not calls:
        logger.warning("Gemini returned no usable content")
        raise LLMError("empty response")
    return LLMReply(
        text=text, tool_calls=calls, raw=content.model_dump(mode="json", exclude_none=True)
    )
