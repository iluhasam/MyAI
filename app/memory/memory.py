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
from app.database.repositories import DialogRepository, OutboxRepository, UserRepository
from app.gateway.payload import UnifiedPayload
from app.llm.base import ChatMessage, LLMClient, Role
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


class MemorySubsystem:
    """Coordinates Session (RAM), Long (SQL) and Semantic (vector) memory."""

    def __init__(self, *, database: Database, llm: LLMClient, session_window: int = 30) -> None:
        self._db = database
        self._session = SessionMemory(window=session_window)
        self._semantic = SemanticMemory(llm)

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
            user_id=user_id, user_key=key, recent_messages=recent, semantic_snippets=snippets
        )

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
