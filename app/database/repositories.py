"""Repositories: focused, testable data-access objects over ORM sessions.

Each repository takes an ``AsyncSession`` (supplied by the caller's transaction),
so several repositories can participate in one atomic unit of work — the basis
for the Outbox pattern, where a domain write and its outbox event commit together.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DialogMessage,
    OutboxEvent,
    OutboxStatus,
    User,
    UserPreference,
)


class UserRepository:
    """CRUD for :class:`User`, keyed by (channel, external_id)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self, *, channel: str, external_id: str, display_name: str | None = None
    ) -> User:
        stmt = select(User).where(User.channel == channel, User.external_id == external_id)
        user = (await self._session.execute(stmt)).scalar_one_or_none()
        if user is None:
            user = User(channel=channel, external_id=external_id, display_name=display_name)
            self._session.add(user)
            await self._session.flush()  # assign PK without ending the transaction
        return user


class PreferenceRepository:
    """Read/write per-user preferences (currently the selected model alias)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_model_alias(self, user_id: int) -> str | None:
        pref = await self._session.get(UserPreference, user_id)
        return pref.model_alias if pref is not None else None

    async def get_persona(self, user_id: int) -> tuple[str | None, str | None]:
        """Return the user's ``(persona_alias, persona_custom)`` or ``(None, None)``."""
        pref = await self._session.get(UserPreference, user_id)
        if pref is None:
            return None, None
        return pref.persona_alias, pref.persona_custom

    async def set_model_alias(self, user_id: int, alias: str) -> None:
        """Upsert the user's model choice (leaves persona untouched)."""
        pref = await self._session.get(UserPreference, user_id)
        if pref is None:
            self._session.add(UserPreference(user_id=user_id, model_alias=alias))
        else:
            pref.model_alias = alias
        await self._session.flush()

    async def set_persona(
        self,
        user_id: int,
        *,
        alias: str | None,
        custom: str | None,
        default_model_alias: str,
    ) -> None:
        """Upsert the user's persona choice (leaves the model choice untouched).

        A row may be created here before the user ever picked a model, so it is
        seeded with ``default_model_alias`` to satisfy the non-null model column.
        """
        pref = await self._session.get(UserPreference, user_id)
        if pref is None:
            pref = UserPreference(user_id=user_id, model_alias=default_model_alias)
            self._session.add(pref)
        pref.persona_alias = alias
        pref.persona_custom = custom
        await self._session.flush()


class DialogRepository:
    """Append/read persistent dialog history (long-term conversation memory)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, user_id: int, role: str, content: str) -> DialogMessage:
        message = DialogMessage(user_id=user_id, role=role, content=content)
        self._session.add(message)
        await self._session.flush()
        return message

    async def recent(self, *, user_id: int, limit: int = 30) -> list[DialogMessage]:
        stmt = (
            select(DialogMessage)
            .where(DialogMessage.user_id == user_id)
            .order_by(DialogMessage.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(reversed(rows))  # chronological order


class OutboxRepository:
    """Transactional Outbox: enqueue events and relay them at-least-once."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, *, event_name: str, payload: dict[str, object]) -> OutboxEvent:
        """Write an event in the *current* transaction (atomic with domain writes)."""
        event = OutboxEvent(event_name=event_name, payload_json=json.dumps(payload, default=str))
        self._session.add(event)
        await self._session.flush()
        return event

    # Statuses eligible for (re)delivery: brand-new and previously-failed rows.
    _DELIVERABLE = (OutboxStatus.PENDING.value, OutboxStatus.FAILED.value)

    async def fetch_deliverable(self, *, limit: int = 100) -> Sequence[OutboxEvent]:
        """Fetch rows awaiting delivery — PENDING or retryable FAILED, oldest first.

        DEAD (dead-lettered) and PUBLISHED rows are terminal and never returned,
        so a poison event can neither be retried forever nor block the queue.
        """
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status.in_(self._DELIVERABLE))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)  # safe concurrent draining (no-op on SQLite)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def count_by_status(self) -> dict[str, int]:
        """Return outbox row counts keyed by status (every status present, default 0)."""
        counts = {status.value: 0 for status in OutboxStatus}
        stmt = select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
        for status, count in (await self._session.execute(stmt)).all():
            counts[status] = count
        return counts

    async def mark_published(self, event_id: int) -> None:
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status=OutboxStatus.PUBLISHED.value, published_at=datetime.now(timezone.utc))
        )

    async def mark_retry(self, event_id: int, *, attempts: int) -> None:
        """A delivery attempt failed but the event is still within its retry budget."""
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status=OutboxStatus.FAILED.value, attempts=attempts)
        )

    async def mark_dead(self, event_id: int, *, attempts: int) -> None:
        """Exhausted the retry budget — move to the dead-letter state (terminal)."""
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status=OutboxStatus.DEAD.value, attempts=attempts)
        )
