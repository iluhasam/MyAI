"""Semantic (associative) memory: retrieve past context by meaning, not recency.

Fragments are embedded via the LLM client and **persisted in the database**, so
associative memory survives restarts (it used to live only in RAM). Retrieval
loads a user's fragments and returns only those whose cosine similarity to the
query exceeds a safety threshold — keeping loosely-related or adversarial context
out of the generation window. Drop-in target for scale: a vector DB (Qdrant).
"""

from __future__ import annotations

import json
import math
from typing import Sequence

from app.core.logger import get_logger
from app.database.database import Database
from app.database.repositories import SemanticRepository
from app.llm.base import LLMClient

_log = get_logger(__name__)

# Only fragments at/above this cosine similarity are injected into the prompt.
DEFAULT_SIMILARITY_THRESHOLD = 0.82


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Standard cosine similarity; returns 0.0 for zero-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class SemanticMemory:
    """Per-user, DB-backed vector store with threshold-gated similarity search."""

    def __init__(
        self,
        llm: LLMClient,
        database: Database,
        *,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._llm = llm
        self._db = database
        self._threshold = threshold

    async def clear(self, user_key: str) -> None:
        """Forget all stored fragments for a user (used by /reset)."""
        async with self._db.session() as session:
            await SemanticRepository(session).delete_for_user(user_key=user_key)

    async def remember(self, user_key: str, text: str) -> None:
        """Embed and persist a fragment for later associative retrieval.

        Auxiliary to the reply: an embedding failure (e.g. provider outage) is
        logged and skipped, never propagated — it must not fail the user's turn.
        """
        if not text.strip():
            return
        vector = await self._safe_embed(text)
        if vector is None:
            return
        async with self._db.session() as session:
            await SemanticRepository(session).add(
                user_key=user_key, text=text, vector_json=json.dumps(vector)
            )

    async def search(self, user_key: str, query: str, *, top_k: int = 3) -> list[str]:
        """Return up to ``top_k`` fragments above the similarity threshold."""
        if not query.strip():
            return []
        async with self._db.session() as session:
            records = await SemanticRepository(session).for_user(user_key=user_key)
        if not records:
            return []
        q_vec = await self._safe_embed(query)
        if q_vec is None:
            return []
        scored = [
            (cosine_similarity(q_vec, json.loads(r.vector_json)), r.text) for r in records
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
