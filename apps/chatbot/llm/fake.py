from typing import ClassVar

from .base import LLMReply


class FakeLLM:
    """Plays scripted replies: an LLMReply, an exception to raise, or a callable."""

    replies: ClassVar[list] = []
    calls: ClassVar[list[dict]] = []

    @classmethod
    def script(cls, *replies):
        cls.replies.extend(replies)

    @classmethod
    def reset(cls):
        cls.replies.clear()
        cls.calls.clear()

    def generate(self, *, system, turns, tools):
        call = {"system": system, "turns": list(turns), "tools": tools}
        self.calls.append(call)
        if not self.replies:
            return LLMReply(text="(fake assistant) Set LLM_PROVIDER=gemini for real answers.")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(**call) if callable(reply) else reply
