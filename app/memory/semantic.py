"""Semantic (associative) memory: retrieve past context by meaning, not recency.

Backed by an in-memory vector index for the MVP (drop-in target: Qdrant). Text
is embedded via the LLM client; retrieval returns only fragments whose cosine
similarity to the query exceeds a safety threshold, preventing loosely-related
or adversarial context from leaking into the generation window.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from app.core.logger import get_logger
from app.llm.base import LLMClient

_log = get_logger(__name__)

# Only fragments at/above this cosine similarity are injected into the prompt.
DEFAULT_SIMILARITY_THRESHOLD = 0.82


@dataclass(slots=True)
class _Record:
    text: str
    vector: list[float]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Standard cosine similarity; returns 0.0 for zero-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class SemanticMemory:
    """Per-user vector store with threshold-gated similarity search."""

    def __init__(self, llm: LLMClient, *, threshold: float = DEFAULT_SIMILARITY_THRESHOLD) -> None:
        self._llm = llm
        self._threshold = threshold
        self._store: dict[str, list[_Record]] = defaultdict(list)

    async def remember(self, user_key: str, text: str) -> None:
        """Embed and store a fragment for later associative retrieval.

        Auxiliary to the reply: an embedding failure (e.g. provider outage) is
        logged and skipped, never propagated — it must not fail the user's turn.
        """
        if not text.strip():
            return
        vectors = await self._safe_embed(text)
        if vectors is None:
            return
        self._store[user_key].append(_Record(text=text, vector=vectors))

    async def search(self, user_key: str, query: str, *, top_k: int = 3) -> list[str]:
        """Return up to ``top_k`` fragments above the similarity threshold."""
        records = self._store.get(user_key)
        if not records or not query.strip():
            return []
        q_vec = await self._safe_embed(query)
        if q_vec is None:
            return []
        scored = [
            (cosine_similarity(q_vec, r.vector), r.text)
            for r in records
        ]
        scored = [pair for pair in scored if pair[0] >= self._threshold]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [text for _, text in scored[:top_k]]

    async def _safe_embed(self, text: str) -> list[float] | None:
        """Embed one text, returning ``None`` (not raising) if the provider fails."""
        try:
            (vector,) = await self._llm.embeddings([text])
            return vector
        except Exception as exc:  # semantic memory is best-effort, never fatal
            _log.warning("embedding failed; skipping semantic memory", extra={"error": str(exc)})
            return None
