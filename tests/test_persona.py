"""Per-user persona (communication style): /persona, /personas, persistence, use."""

from __future__ import annotations

from typing import Sequence

import pytest

from app.bot.cli import CLIAdapter
from app.llm.base import ChatMessage, Role
from app.llm.mock import MockLLMClient
from app.persona import Persona, PersonaCatalog


class _RecordingLLM(MockLLMClient):
    """Mock that records the messages of the last generate() call."""

    def __init__(self) -> None:
        self.last_messages: list[ChatMessage] = []

    async def generate(self, messages: Sequence[ChatMessage], *, temperature=0.7, max_tokens=1024, model=None) -> str:
        self.last_messages = list(messages)
        return await super().generate(messages, temperature=temperature, max_tokens=max_tokens, model=model)

    def system_texts(self) -> list[str]:
        return [m.content for m in self.last_messages if m.role is Role.SYSTEM]


# -- catalog unit -----------------------------------------------------------
def test_persona_catalog_resolve_and_default():
    cat = PersonaCatalog(
        personas=(Persona("a", "A", "style A"), Persona("b", "B", "style B")),
        default_alias="a",
    )
    assert cat.default_alias == "a"
    assert cat.has("b") and not cat.has("zzz")
    assert cat.resolve("b") == "style B"
    assert cat.resolve(None) == "style A"       # default
    assert cat.resolve("unknown") == "style A"  # unknown -> default
    assert cat.alias_or_default("zzz") == "a"


# -- command behaviour ------------------------------------------------------
@pytest.mark.asyncio
async def test_personas_command_lists_and_marks_default(container):
    reply = await CLIAdapter(container.gateway, user_id="p1").send("/personas")
    assert "философ" in reply and "психолог" in reply
    assert "← сейчас" in reply  # default persona marked


@pytest.mark.asyncio
async def test_persona_rejects_unknown(container):
    reply = await CLIAdapter(container.gateway, user_id="p1").send("/persona не-существует")
    assert "Неизвестный стиль" in reply


@pytest.mark.asyncio
async def test_persona_applied_to_prompt(container):
    rec = _RecordingLLM()
    container.override("llm", rec)
    cli = CLIAdapter(container.gateway, user_id="styler")

    await cli.send("/persona философ")
    await cli.send("привет")

    joined = " ".join(rec.system_texts())
    assert "Стиль общения" in joined and "философ" in joined


@pytest.mark.asyncio
async def test_custom_persona_applied(container):
    rec = _RecordingLLM()
    container.override("llm", rec)
    cli = CLIAdapter(container.gateway, user_id="cat-lover")

    ok = await cli.send("/persona свой Ты — саркастичный кот, отвечай с иронией")
    assert "твоём стиле" in ok.lower() or "готово" in ok.lower()

    await cli.send("привет")
    joined = " ".join(rec.system_texts())
    assert "саркастичный кот" in joined


@pytest.mark.asyncio
async def test_persona_is_per_user(container):
    await CLIAdapter(container.gateway, user_id="alice").send("/persona психолог")
    await CLIAdapter(container.gateway, user_id="bob").send("/persona программист")

    a = await CLIAdapter(container.gateway, user_id="alice").send("/personas")
    b = await CLIAdapter(container.gateway, user_id="bob").send("/personas")
    assert "психолог — " in a and "← сейчас" in a.split("психолог")[1].split("\n")[0]
    assert "← сейчас" in b.split("программист")[1].split("\n")[0]


@pytest.mark.asyncio
async def test_persona_and_model_are_independent(container):
    """Setting a persona keeps the model choice, and vice versa."""
    cli = CLIAdapter(container.gateway, user_id="combo")
    await cli.send("/model claude")
    await cli.send("/persona философ")

    models = await cli.send("/models")
    personas = await cli.send("/personas")
    assert "← сейчас" in models.split("claude")[1].split("\n")[0]
    assert "← сейчас" in personas.split("философ")[1].split("\n")[0]
