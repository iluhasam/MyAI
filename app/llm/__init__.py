"""LLM abstraction: a single async interface over many providers.

Exposes ``generate()``, ``vision()`` and ``embeddings()``. The MVP ships a
deterministic ``MockLLMClient`` (no keys, no network); ``build_llm_client``
selects a real LiteLLM-backed client when configured.
"""

from app.llm.base import ChatMessage, LLMClient, Role, wrap_user_input
from app.llm.factory import build_llm_client
from app.llm.mock import MockLLMClient

__all__ = [
    "LLMClient",
    "ChatMessage",
    "Role",
    "wrap_user_input",
    "MockLLMClient",
    "build_llm_client",
]
