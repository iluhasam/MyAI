"""Rate limiting: per-minute burst control and per-day quota, per user."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.bot.cli import CLIAdapter
from app.core.config import Settings
from app.core.container import Container
from app.core.lifecycle import shutdown, startup
from app.core.ratelimit import RateLimiter


class _Clock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_per_minute_limit_and_recovery():
    clock = _Clock()
    rl = RateLimiter(per_minute=2, per_day=100, now=clock)
    assert rl.check("u").allowed
    assert rl.check("u").allowed
    denied = rl.check("u")
    assert not denied.allowed and denied.reason == "minute"
    clock.t += 61  # window slides
    assert rl.check("u").allowed


def test_per_day_limit_and_recovery():
    clock = _Clock()
    rl = RateLimiter(per_minute=1000, per_day=2, now=clock)
    assert rl.check("u").allowed
    clock.t += 61  # stagger to avoid the per-minute cap
    assert rl.check("u").allowed
    clock.t += 61
    denied = rl.check("u")
    assert not denied.allowed and denied.reason == "daily"
    clock.t += 86_400  # a day later
    assert rl.check("u").allowed


def test_denied_requests_are_not_counted():
    clock = _Clock()
    rl = RateLimiter(per_minute=1, per_day=100, now=clock)
    assert rl.check("u").allowed
    assert not rl.check("u").allowed
    assert not rl.check("u").allowed  # repeated denials don't extend the block
    clock.t += 61
    assert rl.check("u").allowed  # exactly one slot frees up


def test_limits_are_per_user():
    rl = RateLimiter(per_minute=1, per_day=100, now=_Clock())
    assert rl.check("a").allowed
    assert not rl.check("a").allowed
    assert rl.check("b").allowed  # a different user is unaffected


@pytest.mark.asyncio
async def test_agent_enforces_and_exempts_commands(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'rl.db'}",
        llm_provider="mock",
        app_log_level="WARNING",
        outbox_publisher_enabled=False,
        rate_limit_enabled=True,
        rate_limit_per_minute=2,
        rate_limit_per_day=100,
    )
    container = Container(settings=settings)
    await startup(container)
    try:
        cli = CLIAdapter(container.gateway, user_id="spammer")
        assert "написали" in (await cli.send("один")).lower()
        assert "написали" in (await cli.send("два")).lower()
        denied = await cli.send("три")
        assert "часто" in denied.lower()  # 3rd LLM turn is throttled
        # Commands stay free even while throttled.
        assert "модель" in (await cli.send("/status")).lower()
    finally:
        await shutdown(container)
