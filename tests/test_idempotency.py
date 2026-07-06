"""Consumer-side idempotency: at-least-once redeliveries run side effects once."""

from __future__ import annotations

import logging

import pytest

from app.bot.cli import CLIAdapter
from app.core.events import Event, EventBus
from app.core.idempotency import IdempotencyGuard
from app.database.models import OutboxEvent, OutboxStatus
from app.database.outbox_publisher import OutboxPublisher
from sqlalchemy import select, update


@pytest.mark.asyncio
async def test_guard_suppresses_duplicate_id():
    calls: list[str] = []
    guard = IdempotencyGuard()

    async def handler(event: Event) -> None:
        calls.append(event.id)

    wrapped = guard.wrap(handler)
    await wrapped(Event(name="e", id="dup"))
    await wrapped(Event(name="e", id="dup"))  # same id -> skipped

    assert calls == ["dup"]
    assert guard.duplicates == 1


@pytest.mark.asyncio
async def test_guard_lets_distinct_ids_through():
    calls: list[str] = []
    guard = IdempotencyGuard()

    async def handler(event: Event) -> None:
        calls.append(event.id)

    wrapped = guard.wrap(handler)
    for eid in ("a", "b", "c"):
        await wrapped(Event(name="e", id=eid))

    assert calls == ["a", "b", "c"]
    assert guard.duplicates == 0


@pytest.mark.asyncio
async def test_guard_evicts_oldest_beyond_window():
    """A duplicate older than the bounded window is no longer recognised."""
    calls: list[str] = []
    guard = IdempotencyGuard(max_size=2)

    async def handler(event: Event) -> None:
        calls.append(event.id)

    wrapped = guard.wrap(handler)
    for eid in ("a", "b", "c"):  # seeing "c" evicts the oldest, "a"
        await wrapped(Event(name="e", id=eid))
    await wrapped(Event(name="e", id="a"))  # "a" fell out of the window -> runs again

    assert calls == ["a", "b", "c", "a"]
    assert guard.duplicates == 0


@pytest.mark.asyncio
async def test_guard_over_the_bus():
    bus = EventBus()
    calls: list[str] = []
    guard = IdempotencyGuard()

    async def handler(event: Event) -> None:
        calls.append(event.id)

    bus.subscribe("evt", guard.wrap(handler))
    await bus.publish(Event(name="evt", id="outbox-1"))
    await bus.publish(Event(name="evt", id="outbox-1"))  # redelivery

    assert calls == ["outbox-1"]
    assert guard.duplicates == 1


@pytest.mark.asyncio
async def test_redelivered_outbox_event_deduped_by_default_subscriber(container, caplog):
    """End-to-end: replaying the same outbox row is suppressed by the guarded subscriber."""
    # A turn enqueues 'message.answered'; startup already wired the guarded subscriber.
    await CLIAdapter(container.gateway, user_id="idem").send("привет")

    async with container.database.session() as session:
        row_id = (await session.execute(select(OutboxEvent))).scalar_one().id

    publisher = OutboxPublisher(container.database, container.event_bus)
    await publisher.drain_once()  # first delivery: subscriber runs

    # Simulate a crash-redelivery: force the (published) row back to pending.
    async with container.database.session() as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == row_id)
            .values(status=OutboxStatus.PENDING.value)
        )

    with caplog.at_level(logging.INFO, logger="app.core.idempotency"):
        await publisher.drain_once()  # second delivery of the SAME stable id

    assert any("duplicate event suppressed" in r.message for r in caplog.records)
