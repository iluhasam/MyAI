"""Default event subscribers wired at application startup.

Gives the durable event stream real consumers in the running app: without a
subscriber the OutboxPublisher would relay ``message.answered`` into the void.
Kept deliberately thin — this is the seam where analytics, notifications, or a
distributed broker fan-out would attach, all decoupled from the cognitive core.
"""

from __future__ import annotations

from app.core.container import Container
from app.core.events import Event
from app.core.idempotency import IdempotencyGuard
from app.core.logger import get_logger

_log = get_logger(__name__)


async def _on_message_answered(event: Event) -> None:
    """Observability hook: record that a turn was durably answered."""
    _log.info(
        "message answered",
        extra={
            "user_key": event.payload.get("user_key"),
            "channel": event.payload.get("channel"),
            "event_id": event.id,
        },
    )


def register_default_subscribers(container: Container) -> None:
    """Attach the platform's built-in event handlers to the bus.

    Handlers are wrapped in an :class:`IdempotencyGuard` so an at-least-once
    redelivery from the Outbox (same stable event id) runs its side effects once.
    Counters feed the ``/metrics`` endpoint: answered turns are counted inside the
    guard (effectively-once), suppressed redeliveries via the guard's callback.
    """
    metrics = container.metrics
    guard = IdempotencyGuard(
        max_size=container.settings.idempotency_cache_size,
        on_duplicate=metrics.inc_duplicate,
    )

    async def on_answered(event: Event) -> None:
        await _on_message_answered(event)
        metrics.inc_turn()

    container.event_bus.subscribe("message.answered", guard.wrap(on_answered))
