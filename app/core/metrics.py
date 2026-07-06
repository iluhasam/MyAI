"""In-process application metrics surfaced via the REST ``/metrics`` endpoint.

Deliberately tiny: plain integer counters incremented from the event-driven
seams (a guarded ``message.answered`` subscriber counts answered turns; the
idempotency guard reports suppressed redeliveries). Durable, DB-backed figures
(outbox backlog by status) are queried on demand instead of mirrored here, so
they can never drift from the source of truth. A production build would swap
this for a Prometheus registry exposing the same series.
"""

from __future__ import annotations


class Metrics:
    """Mutable holder of process-lifetime counters."""

    def __init__(self) -> None:
        self.turns_answered = 0
        self.duplicate_events_suppressed = 0

    def inc_turn(self) -> None:
        self.turns_answered += 1

    def inc_duplicate(self) -> None:
        self.duplicate_events_suppressed += 1

    def snapshot(self) -> dict[str, int]:
        """Return a copy of the current counters (safe to serialise)."""
        return {
            "turns_answered": self.turns_answered,
            "duplicate_events_suppressed": self.duplicate_events_suppressed,
        }
