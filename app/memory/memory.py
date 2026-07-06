"""MemorySubsystem: façade coordinating the three memory tiers.

Responsibilities:
* resolve/persist the user identity (Long memory, PostgreSQL/SQLite);
* assemble a :class:`MemoryContext` (session window + semantic recall) for the
  planner/agent;
* persist each turn to session, long and semantic memory atomically per turn.

Long-term writes reuse the Database's transactional ``session()`` so a user row
and their dialog messages commit together.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logger import get_logger
from app.database.database import Database
from app.database.repositories import (
    DialogRepository,
    OutboxRepository,
    PreferenceRepository,
    UserRepository,
)
from app.gateway.payload import UnifiedPayload
from app.llm.base import ChatMessage, LLMClient, Role
from app.llm.catalog import ModelCatalog
from app.memory.semantic import SemanticMemory
from app.memory.session import SessionMemory

_log = get_logger(__name__)


@dataclass(slots=True)
class MemoryContext:
    """Consolidated context handed to the planner/agent for one turn."""

    user_id: int
    user_key: str
    recent_messages: list[ChatMessage] = field(default_factory=list)
    semantic_snippets: list[str] = field(default_factory=list)
    model_alias: str = ""  # user's selected model alias (or catalog default)
    model: str = ""  # resolved provider model string passed to the LLM client


class MemorySubsystem:
    """Coordinates Session (RAM), Long (SQL) and Semantic (vector) memory."""

    def __init__(
        self,
        *,
        database: Database,
        llm: LLMClient,
        catalog: ModelCatalog,
        session_window: int = 30,
    ) -> None:
        self._db = database
        self._session = SessionMemory(window=session_window)
        self._semantic = SemanticMemory(llm)
        self._catalog = catalog

    @staticmethod
    def user_key(payload: UnifiedPayload) -> str:
        """Stable in-process key combining channel + external id."""
        return f"{payload.channel}:{payload.external_user_id}"

    async def load(self, payload: UnifiedPayload) -> MemoryContext:
        """Resolve the user and build the consolidated context for this turn."""
        key = self.user_key(payload)
        async with self._db.session() as session:
            user = await UserRepository(session).get_or_create(
                channel=payload.channel,
                external_id=payload.external_user_id,
                display_name=payload.display_name,
            )
            user_id = user.id
            stored_alias = await PreferenceRepository(session).get_model_alias(user_id)

        model_alias = self._catalog.alias_or_default(stored_alias)
        model = self._catalog.resolve(model_alias)

        recent = self._session.history(key)
        if not recent:
            # Cold session: rehydrate the window from persistent long memory.
            async with self._db.session() as session:
                rows = await DialogRepository(session).recent(user_id=user_id, limit=20)
            recent = [ChatMessage(role=Role(r.role), content=r.content) for r in rows]
            for msg in recent:
                self._session.append(key, msg)

        snippets = await self._semantic.search(key, payload.text)
        return MemoryContext(
            user_id=user_id,
            user_key=key,
            recent_messages=recent,
            semantic_snippets=snippets,
            model_alias=model_alias,
            model=model,
        )

    async def get_preferred_alias(self, payload: UnifiedPayload) -> str:
        """Return the user's current model alias (or the catalog default)."""
        async with self._db.session() as session:
            user = await UserRepository(session).get_or_create(
                channel=payload.channel,
                external_id=payload.external_user_id,
                display_name=payload.display_name,
            )
            stored = await PreferenceRepository(session).get_model_alias(user.id)
        return self._catalog.alias_or_default(stored)

    async def set_preferred_model(self, payload: UnifiedPayload, alias: str) -> None:
        """Persist the user's model choice (alias must be valid per the catalog)."""
        async with self._db.session() as session:
            user = await UserRepository(session).get_or_create(
                channel=payload.channel,
                external_id=payload.external_user_id,
                display_name=payload.display_name,
            )
            await PreferenceRepository(session).set_model_alias(user.id, alias)

    async def record_turn(
        self, ctx: MemoryContext, *, user_text: str, assistant_text: str, channel: str
    ) -> None:
        """Persist a completed turn to all three tiers.

        The long-memory write and the ``message.answered`` outbox event commit in
        **one transaction** (transactional Outbox): either both land or neither
        does, so a durable event can never be lost or emitted for an un-persisted
        turn. A background :class:`OutboxPublisher` relays it onto the bus.
        """
        user_msg = ChatMessage(role=Role.USER, content=user_text)
        assistant_msg = ChatMessage(role=Role.ASSISTANT, content=assistant_text)

        self._session.append(ctx.user_key, user_msg)
        self._session.append(ctx.user_key, assistant_msg)

        async with self._db.session() as session:
            dialog = DialogRepository(session)
            await dialog.add(user_id=ctx.user_id, role=Role.USER.value, content=user_text)
            await dialog.add(user_id=ctx.user_id, role=Role.ASSISTANT.value, content=assistant_text)
            await OutboxRepository(session).enqueue(
                event_name="message.answered",
                payload={"user_key": ctx.user_key, "user_id": ctx.user_id, "channel": channel},
            )

        await self._semantic.remember(ctx.user_key, user_text)
        _log.debug("turn recorded", extra={"user": ctx.user_key})
