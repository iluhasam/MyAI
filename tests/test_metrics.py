"""Metrics counters fed by the event-driven seams (turns + suppressed dupes)."""

from __future__ import annotations

import pytest

from app.bot.cli import CLIAdapter
from app.database.models import OutboxEvent, OutboxStatus
from app.database.outbox_publisher import OutboxPublisher
from sqlalchemy import select, update


@pytest.mark.asyncio
async def test_turn_counted_once_and_duplicate_tracked(container):
    """A relayed turn is counted once; a redelivery bumps only the duplicate metric."""
    await CLIAdapter(container.gateway, user_id="metric").send("привет")

    async with container.database.session() as session:
        row_id = (await session.execute(select(OutboxEvent))).scalar_one().id

    publisher = OutboxPublisher(container.database, container.event_bus)
    await publisher.drain_once()  # first delivery -> subscriber counts the turn

    assert container.metrics.turns_answered == 1
    assert container.metrics.duplicate_events_suppressed == 0

    # Replay the same row (crash-redelivery): same stable id -> suppressed.
    async with container.database.session() as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == row_id)
            .values(status=OutboxStatus.PENDING.value)
        )
    await publisher.drain_once()

    assert container.metrics.turns_answered == 1  # not double-counted
    assert container.metrics.duplicate_events_suppressed == 1
