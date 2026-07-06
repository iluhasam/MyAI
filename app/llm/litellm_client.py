"""Real LLM client backed by LiteLLM (optional dependency).

LiteLLM unifies OpenAI/Claude/Gemini/DeepSeek/Mistral/Ollama behind one API.
Import is deferred so the package loads even when ``litellm`` isn't installed;
the factory only constructs this client when ``LLM_PROVIDER=litellm``.

Includes bounded retries with exponential backoff for transient overload/rate
errors — the hook where a provider fallback cascade would also be wired in.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from app.core.exceptions import LLMError
from app.core.logger import get_logger
from app.llm.base import ChatMessage

_log = get_logger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 0.5


class LiteLLMClient:
    """Thin adapter over ``litellm.acompletion`` / ``aembedding``."""

    def __init__(self, *, model: str, api_key: str, embedding_model: str | None = None) -> None:
        try:
            import litellm  # noqa: F401  (validate availability early)
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise LLMError(
                "litellm is not installed; run `pip install litellm` or set LLM_PROVIDER=mock"
            ) from exc
        self._model = model
        self._api_key = api_key or None
        # Embeddings need a dedicated embedding model — chat models can't embed.
        self._embedding_model = embedding_model or model

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> str:
        import litellm

        payload = [{"role": m.role.value, "content": m.content} for m in messages]

        async def _call() -> str:
            resp = await litellm.acompletion(
                model=model or self._model,  # per-call override (user-selected model)
                messages=payload,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=self._api_key,
            )
            return resp["choices"][0]["message"]["content"] or ""

        return await self._with_retries(_call)

    async def vision(self, prompt: str, *, image_url: str) -> str:
        import litellm

        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

        async def _call() -> str:
            resp = await litellm.acompletion(
                model=self._model,
                messages=[{"role": "user", "content": content}],
                api_key=self._api_key,
            )
            return resp["choices"][0]["message"]["content"] or ""

        return await self._with_retries(_call)

    async def embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        import litellm

        async def _call() -> list[list[float]]:
            resp = await litellm.aembedding(
                model=self._embedding_model, input=list(texts), api_key=self._api_key
            )
            return [item["embedding"] for item in resp["data"]]

        return await self._with_retries(_call)

    async def _with_retries(self, call):
        """Retry ``call`` on transient errors with exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await call()
            except Exception as exc:  # LiteLLM raises provider-specific errors
                last_exc = exc
                if attempt == _MAX_RETRIES:
                    break
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                _log.warning("LLM call failed; retrying", extra={"attempt": attempt, "delay": delay})
                await asyncio.sleep(delay)
        raise LLMError("LLM request failed after retries") from last_exc
