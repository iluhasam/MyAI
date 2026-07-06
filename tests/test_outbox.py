"""Transactional Outbox tests: atomic enqueue + at-least-once relay."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.bot.cli import CLIAdapter
from app.core.config import Settings
from app.core.container import Container
from app.core.lifecycle import shutdown, startup
from app.database.models import OutboxEvent, OutboxStatus
from app.database.outbox_publisher import OutboxPublisher
from app.database.repositories import OutboxRepository
from sqlalchemy import select


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


@pytest.mark.asyncio
async def test_turn_enqueues_message_answered_atomically(container):
    """A completed turn writes a PENDING 'message.answered' event transactionally."""
    cli = CLIAdapter(container.gateway, user_id="outbox-u1")
    await cli.send("привет")

    async with container.database.session() as session:
        rows = (
            (await session.execute(select(OutboxEvent))).scalars().all()
        )

    assert len(rows) == 1
    event = rows[0]
    assert event.event_name == "message.answered"
    assert event.status == OutboxStatus.PENDING.value  # not relayed yet (publisher off)


@pytest.mark.asyncio
async def test_full_relay_loop_delivers_event_to_bus(tmp_path: Path):
    """End-to-end: turn -> outbox -> background publisher -> bus subscriber."""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'relay.db'}",
        llm_provider="mock",
        app_log_level="WARNING",
        outbox_publisher_enabled=True,  # start the real background relay
        outbox_poll_interval=0.05,      # drain quickly so the test stays fast
    )
    container = Container(settings=settings)

    delivered = asyncio.Event()
    seen: list[str] = []

    async def on_answered(event) -> None:
        seen.append(event.payload.get("user_key", ""))
        delivered.set()

    container.event_bus.subscribe("message.answered", on_answered)

    await startup(container)  # starts the background publisher
    try:
        await CLIAdapter(container.gateway, user_id="relay").send("посчитай 2+2")
        await asyncio.wait_for(delivered.wait(), timeout=3.0)
    finally:
        await shutdown(container)  # stops the publisher, releases the db

    assert seen == ["cli:relay"]
