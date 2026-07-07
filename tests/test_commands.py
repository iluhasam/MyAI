"""UX commands: /status shows current settings, /reset clears the conversation."""

from __future__ import annotations

import pytest

from app.bot.cli import CLIAdapter
from app.database.repositories import DialogRepository, UserRepository


@pytest.mark.asyncio
async def test_status_shows_model_and_persona(container):
    cli = CLIAdapter(container.gateway, user_id="st")
    await cli.send("/model claude")
    await cli.send("/persona философ")

    reply = await cli.send("/status")
    assert "claude" in reply and "философ" in reply


@pytest.mark.asyncio
async def test_status_defaults_when_unset(container):
    reply = await CLIAdapter(container.gateway, user_id="fresh").send("/status")
    assert "gpt-4o-mini" in reply and "обычный" in reply  # catalog defaults


@pytest.mark.asyncio
async def test_reset_clears_history_but_keeps_settings(container):
    cli = CLIAdapter(container.gateway, user_id="rst")
    await cli.send("/model claude")
    await cli.send("запомни первое сообщение")

    # History is persisted before reset.
    async with container.database.session() as session:
        user = await UserRepository(session).get_or_create(channel="cli", external_id="rst")
        assert await DialogRepository(session).recent(user_id=user.id, limit=10)

    reply = await cli.send("/reset")
    assert "чистого листа" in reply.lower()

    # Dialog history is gone...
    async with container.database.session() as session:
        user = await UserRepository(session).get_or_create(channel="cli", external_id="rst")
        assert await DialogRepository(session).recent(user_id=user.id, limit=10) == []

    # ...but the model preference survived.
    assert "claude" in await cli.send("/status")


@pytest.mark.asyncio
async def test_reset_forgets_session_context(container):
    cli = CLIAdapter(container.gateway, user_id="ctx-reset")
    await cli.send("первое сообщение")
    await cli.send("/reset")
    # After reset, a new message must not carry the old one in its echoed context.
    reply = await cli.send("новое сообщение")
    assert "первое сообщение" not in reply
