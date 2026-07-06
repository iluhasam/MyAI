"""Per-user rate limiting (in-process) to cap request volume and cost.

Two rolling windows per user: a short one (requests/minute) that smooths bursts,
and a long one (requests/day) that bounds daily spend. Kept in-process for the
MVP — one limiter per running container; a multi-instance deployment would back
this with Redis (INCR + EXPIRE) so limits are shared across replicas.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque

from app.core.logger import get_logger

_log = get_logger(__name__)

_DAY_SECONDS = 86_400
_MINUTE_SECONDS = 60


class RateDecision:
    """Result of a limit check: allowed, plus a reason when denied."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason


class RateLimiter:
    """Rolling-window limiter keyed by user, enforcing per-minute and per-day caps."""

    def __init__(
        self,
        *,
        per_minute: int,
        per_day: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._per_minute = per_minute
        self._per_day = per_day
        self._now = now
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateDecision:
        """Record a request for ``key`` and decide if it is within the limits.

        A denied request is **not** counted, so a user throttled for a minute can
        retry once the window slides without their rejections extending the block.
        """
        now = self._now()
        hits = self._hits[key]
        # Drop timestamps older than a day so the deque stays bounded (<= per_day).
        cutoff = now - _DAY_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self._per_day:
            _log.info("rate limit hit (daily)", extra={"key": key})
            return RateDecision(False, "daily")

        minute_cutoff = now - _MINUTE_SECONDS
        recent = sum(1 for t in hits if t > minute_cutoff)
        if recent >= self._per_minute:
            _log.info("rate limit hit (per-minute)", extra={"key": key})
            return RateDecision(False, "minute")

        hits.append(now)
        return RateDecision(True)
