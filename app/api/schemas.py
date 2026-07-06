"""Request/response models for the REST API.

These are the *wire contract* of the HTTP channel, kept deliberately separate
from the internal :class:`~app.gateway.payload.UnifiedPayload`/``AgentResponse``
so the public API can evolve without leaking core types.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A single inbound chat message from an API client."""

    user_id: str = Field(
        min_length=1,
        max_length=128,
        description="Stable identifier of the end user within the caller's system.",
    )
    text: str = Field(
        min_length=1,
        max_length=8000,
        description="The user's message. Sanitised server-side before it reaches the LLM.",
    )
    language: str = Field(
        default="ru",
        max_length=8,
        description="BCP-47-ish language hint used for localisation.",
    )


class ChatResponse(BaseModel):
    """The agent's reply rendered back to the API client."""

    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Liveness/readiness probe payload."""

    status: str = "ok"
    env: str


class OutboxCounts(BaseModel):
    """Outbox backlog broken down by delivery status."""

    pending: int = 0
    published: int = 0
    failed: int = 0
    dead: int = 0


class MetricsResponse(BaseModel):
    """Operational counters for scraping/monitoring."""

    turns_answered: int
    duplicate_events_suppressed: int
    outbox: OutboxCounts
