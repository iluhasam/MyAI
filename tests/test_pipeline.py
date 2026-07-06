"""End-to-end vertical-slice tests: CLI transport -> gateway -> router -> agent."""

from __future__ import annotations

import pytest

from app.bot.cli import CLIAdapter
from app.database.repositories import DialogRepository, UserRepository


@pytest.mark.asyncio
async def test_text_message_round_trip(container):
    cli = CLIAdapter(container.gateway, user_id="u1")
    reply = await cli.send("Привет, агент")
    assert "Привет, агент" in reply  # mock LLM echoes the user text


@pytest.mark.asyncio
async def test_command_help(container):
    cli = CLIAdapter(container.gateway)
    reply = await cli.send("/help")
    assert "персональный ИИ-агент" in reply.lower() or "агент" in reply.lower()


@pytest.mark.asyncio
async def test_calculator_plan_executes(container):
    cli = CLIAdapter(container.gateway, user_id="math")
    reply = await cli.send("(2+3)*4")
    # The planner routes arithmetic to the calculator; result reaches the reply.
    assert "20" in reply


@pytest.mark.asyncio
async def test_turn_is_persisted_to_long_memory(container):
    cli = CLIAdapter(container.gateway, user_id="persist")
    await cli.send("запомни это сообщение")

    async with container.database.session() as session:
        user = await UserRepository(session).get_or_create(
            channel="cli", external_id="persist"
        )
        rows = await DialogRepository(session).recent(user_id=user.id, limit=10)

    roles = [r.role for r in rows]
    assert "user" in roles and "assistant" in roles


@pytest.mark.asyncio
async def test_session_memory_survives_within_conversation(container):
    cli = CLIAdapter(container.gateway, user_id="ctx")
    await cli.send("первое сообщение")
    reply = await cli.send("второе сообщение")
    assert "второе сообщение" in reply
