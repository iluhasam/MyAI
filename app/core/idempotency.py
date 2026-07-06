"""Consumer-side idempotency: turn at-least-once delivery into effectively-once.

The Outbox relays events *at-least-once* — a crash between publishing and marking
a row PUBLISHED causes a redelivery. Consumers that have side effects must
therefore be idempotent. :class:`IdempotencyGuard` wraps a handler and skips any
event whose id it has already processed, keyed on the **stable** id the publisher
assigns (``outbox-<row_id>``).

The dedup window is bounded (FIFO eviction) so memory stays flat; a duplicate
older than the window may slip through — an acceptable trade for a crash-recovery
window measured in seconds. A distributed deployment would back this with Redis
(e.g. ``SET key NX EX``) instead of an in-process set.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from app.core.events import Event, Handler
from app.core.logger import get_logger

_log = get_logger(__name__)


class IdempotencyGuard:
    """Bounded, in-process dedup for a single event handler.

    Use one guard per wrapped handler: ``bus.subscribe(name, guard.wrap(fn))``.
    Sharing a guard across handlers would let one handler's processing suppress
    another's, since they see the same event id.
    """

    def __init__(
        self, *, max_size: int = 10_000, on_duplicate: Callable[[], None] | None = None
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = max_size
        self._on_duplicate = on_duplicate
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.duplicates = 0  # observability counter: how many redeliveries were skipped

    def _mark(self, event_id: str) -> bool:
        """Record ``event_id``; return True if it was already present (a duplicate)."""
        if event_id in self._seen:
            self._seen.move_to_end(event_id)  # refresh recency so hot ids aren't evicted
            return True
        self._seen[event_id] = None
        if len(self._seen) > self._max_size:
            self._seen.popitem(last=False)  # evict the oldest id
        return False

    def wrap(self, handler: Handler) -> Handler:
        """Return ``handler`` guarded so already-seen event ids are skipped."""

        async def guarded(event: Event) -> None:
            if self._mark(event.id):
                self.duplicates += 1
                if self._on_duplicate is not None:
                    self._on_duplicate()
                _log.info("duplicate event suppressed", extra={"event_id": event.id})
                return
            await handler(event)

        return guarded
