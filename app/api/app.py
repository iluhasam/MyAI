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

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.core.container import Container
from app.core.lifecycle import shutdown, startup
from app.core.logger import get_logger
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
