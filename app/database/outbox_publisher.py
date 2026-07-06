"""Background Outbox publisher — the relay half of the Outbox pattern.

Polls the ``outbox_events`` table for PENDING rows and republishes them onto the
in-process :class:`EventBus` (or, in a larger deployment, a distributed broker).
Each event is marked PUBLISHED in its own transaction, so a crash mid-run simply
leaves the row PENDING and it is retried next tick — at-least-once semantics.
"""

from __future__ import annotations

import asyncio
import json

from app.core.events import Event, EventBus
from app.core.logger import get_logger
from app.database.database import Database
from app.database.repositories import OutboxRepository

_log = get_logger(__name__)


class OutboxPublisher:
    """Periodically drains the outbox and emits events onto the bus."""

    def __init__(self, database: Database, event_bus: EventBus, *, interval: float = 1.0) -> None:
        self._db = database
        self._bus = event_bus
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def drain_once(self, *, batch: int = 100) -> int:
        """Publish up to ``batch`` pending events. Returns the number published."""
        published = 0
        async with self._db.session() as session:
            repo = OutboxRepository(session)
            for row in await repo.fetch_pending(limit=batch):
                try:
                    payload = json.loads(row.payload_json)
                    await self._bus.publish(Event(name=row.event_name, payload=payload))
                    await repo.mark_published(row.id)
                    published += 1
                except Exception:  # keep draining others; row stays retryable
                    _log.exception("failed to publish outbox event", extra={"id": row.id})
                    await repo.mark_failed(row.id)
        return published

    async def _run(self) -> None:
        _log.info("outbox publisher started")
        while not self._stopped.is_set():
            try:
                await self.drain_once()
            except Exception:  # never let the loop die on transient DB errors
                _log.exception("outbox drain cycle failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue
        _log.info("outbox publisher stopped")

    def start(self) -> None:
        if self._task is None:
            self._stopped.clear()
            self._task = asyncio.create_task(self._run(), name="outbox-publisher")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            await self._task
            self._task = None
