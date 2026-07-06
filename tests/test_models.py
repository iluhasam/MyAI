"""Per-user model selection: /models, /model <alias>, persistence, and use."""

from __future__ import annotations

import pytest

from app.bot.cli import CLIAdapter
from app.llm.catalog import ModelCatalog, ModelInfo


# -- catalog unit -----------------------------------------------------------
def test_catalog_resolve_and_default():
    cat = ModelCatalog(
        models=(
            ModelInfo("a", "prov/model-a", "A"),
            ModelInfo("b", "prov/model-b", "B"),
        ),
        default_alias="b",
    )
    assert cat.default_alias == "b"
    assert cat.has("a") and not cat.has("zzz")
    assert cat.resolve("a") == "prov/model-a"
    assert cat.resolve(None) == "prov/model-b"      # default
    assert cat.resolve("unknown") == "prov/model-b"  # unknown -> default
    assert cat.alias_or_default("zzz") == "b"


def test_catalog_bad_default_falls_back_to_first():
    cat = ModelCatalog(models=(ModelInfo("only", "p/m", "M"),), default_alias="missing")
    assert cat.default_alias == "only"


# -- command behaviour ------------------------------------------------------
@pytest.mark.asyncio
async def test_models_command_lists_catalog(container):
    cli = CLIAdapter(container.gateway, user_id="u1")
    reply = await cli.send("/models")
    assert "gpt-4o-mini" in reply and "claude" in reply
    assert "← сейчас" in reply  # marks the current (default) model


@pytest.mark.asyncio
async def test_model_command_rejects_unknown(container):
    cli = CLIAdapter(container.gateway, user_id="u1")
    reply = await cli.send("/model definitely-not-a-model")
    assert "Неизвестная модель" in reply


@pytest.mark.asyncio
async def test_model_selection_persists_and_is_used(container):
    cli = CLIAdapter(container.gateway, user_id="picky")
    ok = await cli.send("/model claude")
    assert "claude" in ok.lower()

    # The next turn must run through the selected model — the mock echoes it.
    reply = await cli.send("привет")
    assert "claude" in reply  # e.g. [mock-llm:openrouter/anthropic/claude-3.5-sonnet]


@pytest.mark.asyncio
async def test_selection_is_per_user(container):
    alice = CLIAdapter(container.gateway, user_id="alice")
    bob = CLIAdapter(container.gateway, user_id="bob")

    await alice.send("/model claude")
    await bob.send("/model gemini")

    assert "claude" in await alice.send("hi")
    assert "gemini" in await bob.send("hi")  # bob's choice is independent of alice's


@pytest.mark.asyncio
async def test_default_model_used_when_unset(container):
    cli = CLIAdapter(container.gateway, user_id="fresh")
    reply = await cli.send("привет")
    assert "gpt-4o-mini" in reply  # catalog default
