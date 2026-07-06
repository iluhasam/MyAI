"""Gateway layer: normalise + sanitise inbound requests into a UnifiedPayload."""

from app.gateway.gateway import Gateway
from app.gateway.payload import (
    AgentResponse,
    Attachment,
    MessageType,
    UnifiedPayload,
)
from app.gateway.sanitizer import sanitize_text

__all__ = [
    "Gateway",
    "UnifiedPayload",
    "AgentResponse",
    "Attachment",
    "MessageType",
    "sanitize_text",
]
