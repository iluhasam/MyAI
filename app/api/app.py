"""FastAPI application factory for the REST transport.

``create_api(container)`` returns a fully-wired ASGI app. The platform's own
startup/shutdown (DB connect, schema, teardown) is bridged into FastAPI's
lifespan so serving the API brings the exact same resources up and down as the
CLI/Telegram entrypoints — no duplicated wiring.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.miniapp_page import MINIAPP_HTML
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MetricsResponse,
    ModelOut,
    ModelsResponse,
    OutboxCounts,
    PersonaOut,
    PersonasResponse,
)
from app.api.telegram_auth import verify_init_data
from app.core.container import Container
from app.core.lifecycle import shutdown, startup
from app.core.logger import get_logger
from app.database.repositories import OutboxRepository
from app.gateway.gateway import RawInbound
from app.gateway.payload import MessageType, UnifiedPayload

_log = get_logger(__name__)


class _AliasIn(BaseModel):
    alias: str


def create_api(container: Container, *, manage_lifecycle: bool = True) -> FastAPI:
    """Build the REST API over a :class:`Container`.

    When ``manage_lifecycle`` is True (default) the app runs the platform
    startup/shutdown via FastAPI's lifespan. In the combined ``all`` transport a
    single outer runner owns the lifecycle, so it passes ``False`` to avoid a
    double startup.
    """

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        if manage_lifecycle:
            await startup(container)
        try:
            yield
        finally:
            if manage_lifecycle:
                await shutdown(container)

    app = FastAPI(
        title="AI Agent Platform API",
        version="0.1.0",
        summary="HTTP channel over the transport-agnostic cognitive core.",
        lifespan=_lifespan,
    )

    def _require_tg_user(authorization: str = Header(default="")) -> dict:
        """Authenticate a Mini App request from the 'Authorization: tma <initData>' header."""
        if not authorization.startswith("tma "):
            raise HTTPException(status_code=401, detail="missing Telegram init data")
        user = verify_init_data(authorization[4:], container.settings.telegram_bot_token)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid Telegram init data")
        return user

    def _payload_for(user: dict) -> UnifiedPayload:
        return UnifiedPayload(
            channel="telegram",
            external_user_id=str(user["id"]),
            message_type=MessageType.TEXT,
            display_name=user.get("first_name"),
        )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    async def health() -> HealthResponse:
        """Liveness probe: confirms the process is up and reports the env."""
        return HealthResponse(env=container.settings.app_env.value)

    @app.get("/metrics", response_model=MetricsResponse, tags=["ops"])
    async def metrics() -> MetricsResponse:
        """Operational counters: answered turns, suppressed dupes, outbox backlog."""
        async with container.database.session() as session:
            outbox = await OutboxRepository(session).count_by_status()
        snap = container.metrics.snapshot()
        return MetricsResponse(
            turns_answered=snap["turns_answered"],
            duplicate_events_suppressed=snap["duplicate_events_suppressed"],
            outbox=OutboxCounts(**outbox),
        )

    @app.get("/models", response_model=ModelsResponse, tags=["chat"])
    async def models() -> ModelsResponse:
        """List selectable models. Users switch with the `/model <alias>` command."""
        catalog = container.catalog
        return ModelsResponse(
            default=catalog.default_alias,
            models=[ModelOut(alias=m.alias, label=m.label) for m in catalog.list()],
        )

    @app.get("/personas", response_model=PersonasResponse, tags=["chat"])
    async def personas() -> PersonasResponse:
        """List communication styles. Users switch with `/persona <alias>`."""
        cat = container.personas
        return PersonasResponse(
            default=cat.default_alias,
            personas=[PersonaOut(alias=p.alias, label=p.label) for p in cat.list()],
        )

    # -- Mini App (settings UI inside Telegram) ----------------------------
    @app.get("/app", response_class=HTMLResponse, tags=["miniapp"])
    async def mini_app_page() -> str:
        """Serve the Telegram Mini App settings page."""
        return MINIAPP_HTML

    @app.get("/miniapp/state", tags=["miniapp"])
    async def mini_state(user: dict = Depends(_require_tg_user)) -> dict:
        """Current model/persona for the authenticated user + the full catalogs."""
        payload = _payload_for(user)
        current_model = await container.memory.get_preferred_alias(payload)
        current_persona = await container.memory.get_persona_alias(payload)
        return {
            "user_name": user.get("first_name", ""),
            "models": [
                {"alias": m.alias, "label": m.label, "current": m.alias == current_model}
                for m in container.catalog.list()
            ],
            "personas": [
                {"alias": p.alias, "label": p.label, "current": p.alias == current_persona}
                for p in container.personas.list()
            ],
        }

    @app.post("/miniapp/model", tags=["miniapp"])
    async def mini_set_model(body: _AliasIn, user: dict = Depends(_require_tg_user)) -> dict:
        if not container.catalog.has(body.alias):
            raise HTTPException(status_code=400, detail="unknown model")
        await container.memory.set_preferred_model(_payload_for(user), body.alias)
        return {"ok": True, "model": body.alias}

    @app.post("/miniapp/persona", tags=["miniapp"])
    async def mini_set_persona(body: _AliasIn, user: dict = Depends(_require_tg_user)) -> dict:
        if not container.personas.has(body.alias):
            raise HTTPException(status_code=400, detail="unknown persona")
        applied_model = await container.memory.apply_persona(_payload_for(user), body.alias)
        return {"ok": True, "persona": body.alias, "model": applied_model}

    @app.post("/miniapp/reset", tags=["miniapp"])
    async def mini_reset(user: dict = Depends(_require_tg_user)) -> dict:
        await container.memory.reset(_payload_for(user))
        return {"ok": True}

    @app.post("/chat", response_model=ChatResponse, tags=["chat"])
    async def chat(req: ChatRequest) -> ChatResponse:
        """Run one full cognitive turn for ``req`` and return the agent's reply."""
        raw: RawInbound = {
            "channel": "api",
            "external_user_id": req.user_id,
            "message_type": "command" if req.text.startswith("/") else "text",
            "text": req.text,
            "language": req.language,
        }
        response = await container.gateway.handle(raw)
        return ChatResponse(text=response.text, metadata=dict(response.metadata))

    return app
