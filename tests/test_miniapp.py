"""Mini App: initData signature verification + authenticated settings endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_api
from app.api.telegram_auth import verify_init_data
from app.core.config import Settings
from app.core.container import Container

_TOKEN = "123456:TEST-BOT-TOKEN"


def _make_init_data(token: str = _TOKEN, *, user_id: int = 42, name: str = "Тест", age: int = 0) -> str:
    user = json.dumps({"id": user_id, "first_name": name}, ensure_ascii=False)
    fields = {"auth_date": str(int(time.time()) - age), "user": user, "query_id": "AAA"}
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


# -- signature verification -------------------------------------------------
def test_valid_init_data_accepted():
    user = verify_init_data(_make_init_data(), _TOKEN)
    assert user and user["id"] == 42 and user["first_name"] == "Тест"


def test_tampered_hash_rejected():
    data = _make_init_data()
    assert verify_init_data(data + "0", _TOKEN) is None  # mangled tail


def test_wrong_token_rejected():
    assert verify_init_data(_make_init_data(), "999:OTHER-TOKEN") is None


def test_missing_hash_rejected():
    assert verify_init_data("user=%7B%7D&auth_date=1", _TOKEN) is None


def test_expired_rejected():
    old = _make_init_data(age=100_000)  # older than the default max age
    assert verify_init_data(old, _TOKEN) is None


# -- endpoints --------------------------------------------------------------
@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'mini.db'}",
        llm_provider="mock",
        app_log_level="WARNING",
        outbox_publisher_enabled=False,
        rate_limit_enabled=False,
        telegram_bot_token=_TOKEN,
    )
    with TestClient(create_api(Container(settings=settings))) as c:
        yield c


def _auth():
    return {"Authorization": "tma " + _make_init_data()}


def test_page_served(client: TestClient):
    r = client.get("/app")
    assert r.status_code == 200 and "telegram-web-app.js" in r.text


def test_state_requires_auth(client: TestClient):
    assert client.get("/miniapp/state").status_code == 401


def test_state_and_set_model(client: TestClient):
    st = client.get("/miniapp/state", headers=_auth()).json()
    assert st["user_name"] == "Тест"
    assert any(m["alias"] == "claude" for m in st["models"])

    assert client.post("/miniapp/model", json={"alias": "claude"}, headers=_auth()).status_code == 200
    st2 = client.get("/miniapp/state", headers=_auth()).json()
    assert next(m for m in st2["models"] if m["alias"] == "claude")["current"]


def test_set_persona_auto_selects_model(client: TestClient):
    r = client.post("/miniapp/persona", json={"alias": "хам"}, headers=_auth()).json()
    assert r["model"] == "deepseek"
    st = client.get("/miniapp/state", headers=_auth()).json()
    assert next(p for p in st["personas"] if p["alias"] == "хам")["current"]
    assert next(m for m in st["models"] if m["alias"] == "deepseek")["current"]


def test_unknown_model_rejected(client: TestClient):
    assert client.post("/miniapp/model", json={"alias": "nope"}, headers=_auth()).status_code == 400


def test_reset_ok(client: TestClient):
    assert client.post("/miniapp/reset", json={}, headers=_auth()).json()["ok"]
