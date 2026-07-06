"""Transactional Outbox tests: atomic enqueue + at-least-once relay."""

from __future__ import annotations

import pytest

from app.database.outbox_publisher import OutboxPublisher
from app.database.repositories import OutboxRepository


@pytest.mark.asyncio
async def test_outbox_enqueue_and_publish(container):
    bus = container.event_bus
    received: list[str] = []

    async def handler(event) -> None:
        received.append(event.payload.get("kind", ""))

    bus.subscribe("task.created", handler)

    # Domain write + event enqueue would share one transaction in real code;
    # here we enqueue directly to test the relay half.
    async with container.database.session() as session:
        await OutboxRepository(session).enqueue(
            event_name="task.created", payload={"kind": "unit-test"}
        )

    publisher = OutboxPublisher(container.database, bus)
    published = await publisher.drain_once()

    assert published == 1
    assert received == ["unit-test"]


@pytest.mark.asyncio
async def test_outbox_marks_published(container):
    async with container.database.session() as session:
        await OutboxRepository(session).enqueue(event_name="noop.event", payload={})

    publisher = OutboxPublisher(container.database, container.event_bus)
    await publisher.drain_once()
    # A second drain finds nothing pending — proves rows are marked published.
    assert await publisher.drain_once() == 0
