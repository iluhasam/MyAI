"""Factory that selects an LLM client implementation from settings.

Keeps provider-selection logic in one place so the DI container stays declarative.
Unknown providers fail loud at startup rather than silently degrading.
"""

from __future__ import annotations

import os

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.logger import get_logger
from app.llm.base import LLMClient
from app.llm.mock import MockLLMClient

_log = get_logger(__name__)


def build_llm_client(settings: Settings) -> LLMClient:
    """Return a concrete ``LLMClient`` for the configured provider.

    The concrete model per request is chosen by the caller (per-user selection);
    the value passed here is only the fallback default.
    """
    provider = settings.llm_provider.lower()
    # Convenience: if an OpenRouter key is present but LLM_PROVIDER was left at the
    # default 'mock', use OpenRouter automatically (a common deploy misconfiguration
    # that otherwise silently serves the echo mock).
    if provider == "mock" and settings.openrouter_api_key:
        _log.info("OPENROUTER_API_KEY is set but LLM_PROVIDER=mock — using OpenRouter")
        provider = "openrouter"
    if provider == "mock":
        _log.info("using MockLLMClient (deterministic, offline)")
        return MockLLMClient()
    if provider == "litellm":
        from app.llm.litellm_client import LiteLLMClient

        _log.info("using LiteLLMClient", extra={"model": settings.llm_model})
        return LiteLLMClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            embedding_model=settings.llm_embedding_model or None,
        )
    if provider == "openrouter":
        from app.llm.catalog import ModelCatalog
        from app.llm.litellm_client import LiteLLMClient

        key = settings.openrouter_api_key or settings.llm_api_key
        if not key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY is empty; set it in .env or use LLM_PROVIDER=mock"
            )
        # Multi-provider routing: LiteLLM picks the provider from the model prefix
        # (openrouter/* vs gemini/*) and reads that provider's key from the env.
        # We therefore set env keys and pass NO per-call api_key, so each model
        # reaches its own provider with its own credentials.
        os.environ["OPENROUTER_API_KEY"] = key
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        catalog = ModelCatalog(default_alias=settings.default_model)
        fallback = catalog.resolve(catalog.default_alias)
        embedding_model = settings.llm_embedding_model or "openrouter/openai/text-embedding-3-small"
        _log.info(
            "using multi-provider LiteLLM (OpenRouter + direct Gemini)",
            extra={"default_model": fallback, "embedding_model": embedding_model},
        )
        return LiteLLMClient(model=fallback, api_key=None, embedding_model=embedding_model)
    raise ConfigurationError(f"unknown LLM_PROVIDER={settings.llm_provider!r}")
