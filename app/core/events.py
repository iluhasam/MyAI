"""Asynchronous in-process event bus (Event-Driven Architecture).

Decouples components: publishers emit typed events without knowing subscribers.
Handlers are coroutine callables; they run concurrently and are isolated so a
single failing handler never breaks the others or the publisher. This bus is the
in-process transport; the Outbox pattern (see app.database) provides the durable,
at-least-once counterpart for cross-process/distributed delivery.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import uuid4

from app.core.logger import get_logger

_log = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class Event:
    """An immutable domain event.

    ``name`` is the routing key (e.g. ``"message.received"``); ``payload`` carries
    arbitrary structured data. ``id`` and ``created_at`` support tracing/idempotency.
    """

    name: str
    payload: dict[str, object] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Minimal async pub/sub bus with concurrent, fault-isolated dispatch."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Handler) -> None:
        """Register a coroutine handler for events named ``event_name``."""
        self._handlers[event_name].append(handler)
        _log.debug("event handler subscribed", extra={"event": event_name})

    async def publish(self, event: Event) -> None:
        """Dispatch ``event`` to all subscribers concurrently.

        Exceptions raised by individual handlers are logged and swallowed so one
        misbehaving subscriber cannot poison the others.
        """
        handlers = list(self._handlers.get(event.name, ()))
        if not handlers:
            _log.debug("event had no subscribers", extra={"event": event.name})
            return
        results = await asyncio.gather(
            *(h(event) for h in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                _log.error(
                    "event handler failed",
                    extra={"event": event.name, "handler": getattr(handler, "__qualname__", handler)},
                    exc_info=result,
                )
