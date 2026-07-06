"""Deterministic mock LLM — the default provider for a zero-config MVP run.

Produces stable, inspectable output so the whole pipeline (and tests) run with no
network or API key. It echoes the last user message and, when the executor has
attached tool results to the system context, folds them into the reply. Embeddings
are a cheap deterministic hash so semantic memory works offline too.
"""

from __future__ import annotations

import hashlib
import math
from typing import Sequence

from app.llm.base import ChatMessage, Role

_EMBED_DIM = 64


class MockLLMClient:
    """A dependency-free, deterministic stand-in for a real LLM provider."""

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role is Role.USER), ""
        )
        tool_context = " ".join(
            m.content for m in messages if m.role is Role.SYSTEM and "TOOL_RESULT" in m.content
        )
        # Echo the selected model so model-selection is observable offline (tests).
        tag = f"mock-llm:{model}" if model else "mock-llm"
        reply = f"[{tag}] Вы написали: {last_user.strip()[:500]}"
        if tool_context:
            reply += f"\nРезультаты инструментов учтены: {tool_context.strip()[:500]}"
        return reply

    async def vision(self, prompt: str, *, image_url: str) -> str:
        return f"[mock-vision] Изображение по адресу {image_url}: описание недоступно в mock-режиме."

    async def embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    @staticmethod
    def _embed(text: str) -> list[float]:
        """Deterministic, L2-normalised pseudo-embedding derived from a hash."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [
            digest[i % len(digest)] - 127.5  # centre around zero
            for i in range(_EMBED_DIM)
        ]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]
