"""REST API tests: the HTTP channel over the same Gateway/Router/Agent stack.

Uses FastAPI's TestClient, whose context manager drives the app lifespan (DB
connect/schema on enter, teardown on exit) against a throwaway SQLite file and
the deterministic mock LLM — no network, no external services.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_api
from app.core.config import Settings
from app.core.container import Container


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        llm_provider="mock",
        app_log_level="WARNING",
    )
    app = create_api(Container(settings=settings))
    with TestClient(app) as c:  # __enter__ runs the lifespan (startup/shutdown)
        yield c


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["env"] == "dev"


def test_chat_echoes_user_text(client: TestClient):
    resp = client.post("/chat", json={"user_id": "api-u1", "text": "Привет, агент"})
    assert resp.status_code == 200
    assert "Привет, агент" in resp.json()["text"]  # mock LLM echoes


def test_chat_calculator(client: TestClient):
    resp = client.post("/chat", json={"user_id": "math", "text": "(2+3)*4"})
    assert resp.status_code == 200
    assert "20" in resp.json()["text"]


def test_chat_validation_rejects_empty_text(client: TestClient):
    resp = client.post("/chat", json={"user_id": "u", "text": ""})
    assert resp.status_code == 422  # pydantic min_length violation


def test_session_memory_persists_across_requests(client: TestClient):
    client.post("/chat", json={"user_id": "ctx", "text": "первое сообщение"})
    resp = client.post("/chat", json={"user_id": "ctx", "text": "второе сообщение"})
    assert "второе сообщение" in resp.json()["text"]
