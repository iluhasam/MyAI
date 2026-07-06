"""Factory that selects an LLM client implementation from settings.

Keeps provider-selection logic in one place so the DI container stays declarative.
Unknown providers fail loud at startup rather than silently degrading.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.logger import get_logger
from app.llm.base import LLMClient
from app.llm.mock import MockLLMClient

_log = get_logger(__name__)


def build_llm_client(settings: Settings) -> LLMClient:
    """Return a concrete ``LLMClient`` for the configured provider."""
    provider = settings.llm_provider.lower()
    if provider == "mock":
        _log.info("using MockLLMClient (deterministic, offline)")
        return MockLLMClient()
    if provider == "litellm":
        from app.llm.litellm_client import LiteLLMClient

        _log.info("using LiteLLMClient", extra={"model": settings.llm_model})
        return LiteLLMClient(model=settings.llm_model, api_key=settings.llm_api_key)
    raise ConfigurationError(f"unknown LLM_PROVIDER={settings.llm_provider!r}")
