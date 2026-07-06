"""FastAPI application factory for the REST transport.

``create_api(container)`` returns a fully-wired ASGI app. The platform's own
startup/shutdown (DB connect, schema, teardown) is bridged into FastAPI's
lifespan so serving the API brings the exact same resources up and down as the
CLI/Telegram entrypoints — no duplicated wiring.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

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
from app.core.container import Container
from app.core.lifecycle import shutdown, startup
from app.core.logger import get_logger
from app.database.repositories import OutboxRepository
from app.gateway.gateway import RawInbound

_log = get_logger(__name__)


def create_api(container: Container) -> FastAPI:
    """Build the REST API over a (not-yet-started) :class:`Container`.

    The container's resources are initialised on app startup and released on
    shutdown, so the caller just hands over a freshly-built composition root.
    """

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        await startup(container)
        try:
            yield
        finally:
            await shutdown(container)

    app = FastAPI(
        title="AI Agent Platform API",
        version="0.1.0",
        summary="HTTP channel over the transport-agnostic cognitive core.",
        lifespan=_lifespan,
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
