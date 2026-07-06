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

    def __init__(
        self,
        database: Database,
        event_bus: EventBus,
        *,
        interval: float = 1.0,
        max_attempts: int = 5,
    ) -> None:
        self._db = database
        self._bus = event_bus
        self._interval = interval
        self._max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def drain_once(self, *, batch: int = 100) -> int:
        """Relay up to ``batch`` deliverable events. Returns the number published.

        Failures are retried on later ticks (status FAILED) until the attempt
        budget is spent, after which the row is dead-lettered (status DEAD) so a
        single poison event never blocks the queue or loops forever. The relayed
        event carries a **stable id** derived from the row, so a redelivery after
        a crash is deduplicable by idempotent consumers.
        """
        published = 0
        async with self._db.session() as session:
            repo = OutboxRepository(session)
            for row in await repo.fetch_deliverable(limit=batch):
                try:
                    payload = json.loads(row.payload_json)
                    event = Event(
                        name=row.event_name, payload=payload, id=f"outbox-{row.id}"
                    )
                    await self._bus.publish(event)
                    await repo.mark_published(row.id)
                    published += 1
                except Exception:
                    attempts = row.attempts + 1
                    if attempts >= self._max_attempts:
                        _log.error(
                            "outbox event dead-lettered (retries exhausted)",
                            extra={"id": row.id, "event": row.event_name, "attempts": attempts},
                        )
                        await repo.mark_dead(row.id, attempts=attempts)
                    else:
                        _log.warning(
                            "outbox publish failed; will retry",
                            extra={"id": row.id, "event": row.event_name, "attempts": attempts},
                        )
                        await repo.mark_retry(row.id, attempts=attempts)
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
