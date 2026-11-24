from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import LLMClient
from .fake import FakeLLM


def get_llm() -> LLMClient:
    """The model selected by `settings.LLM_PROVIDER`."""
    if settings.LLM_PROVIDER == "fake":
        return FakeLLM()
    if settings.LLM_PROVIDER == "gemini":
        # Local import: the SDK is slow to load and only workers need it.
        from .gemini import GeminiClient

        return GeminiClient()
    raise ImproperlyConfigured(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER!r}")
