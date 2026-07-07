"""Inline buttons: the Agent describes keyboards; transports render them."""

from __future__ import annotations

import pytest

from app.gateway.gateway import RawInbound


def _cmd(command: str, *, user: str = "b1") -> RawInbound:
    return {
        "channel": "cli",
        "external_user_id": user,
        "message_type": "command",
        "text": "/" + command,
        "command": command.split()[0],
    }


def _actions(resp) -> list[str]:
    return [b.action for row in resp.buttons for b in row]


def _labels(resp) -> list[str]:
    return [b.label for row in resp.buttons for b in row]


@pytest.mark.asyncio
async def test_menu_has_setting_buttons(container):
    resp = await container.gateway.handle(_cmd("menu"))
    assert set(_actions(resp)) >= {"models", "personas", "status", "reset"}


@pytest.mark.asyncio
async def test_start_shows_menu(container):
    resp = await container.gateway.handle(_cmd("start"))
    assert _actions(resp)  # /start opens the button menu too


@pytest.mark.asyncio
async def test_models_buttons_one_per_model_plus_back(container):
    resp = await container.gateway.handle(_cmd("models"))
    actions = _actions(resp)
    assert "model claude" in actions and "model gpt-4o-mini" in actions
    assert "menu" in actions  # back button


@pytest.mark.asyncio
async def test_current_model_marked_on_button(container):
    await container.gateway.handle(_cmd("model claude", user="marked"))
    resp = await container.gateway.handle(_cmd("models", user="marked"))
    assert any(lbl.startswith("✅") and "claude" in lbl for lbl in _labels(resp))


@pytest.mark.asyncio
async def test_personas_buttons_and_confirmation_back(container):
    resp = await container.gateway.handle(_cmd("personas"))
    assert "persona философ" in _actions(resp) and "menu" in _actions(resp)

    done = await container.gateway.handle(_cmd("persona философ"))
    assert _actions(done) == ["menu"]  # confirmation offers a Back button


@pytest.mark.asyncio
async def test_status_offers_change_buttons(container):
    resp = await container.gateway.handle(_cmd("status"))
    assert set(_actions(resp)) == {"models", "personas"}
