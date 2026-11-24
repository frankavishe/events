from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """The model could not produce a usable answer."""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class LLMReply:
    """`raw` is the provider's own JSON form of this message, replayed unchanged in history."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict | None = None


@dataclass
class Turn:
    """`role` is user, model or tool. Results are `{"id", "name", "response"}`."""

    role: str
    text: str = ""
    raw: dict | None = None
    results: list[dict] = field(default_factory=list)


class LLMClient(Protocol):
    def generate(self, *, system: str, turns: list[Turn], tools: list[dict]) -> LLMReply:
        """`tools` are `{"name", "description", "parameters": JSON schema}`. Raises LLMError."""
        ...
