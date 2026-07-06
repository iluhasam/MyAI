"""Canonical, channel-agnostic data contracts (Pydantic v2).

``UnifiedPayload`` is the single internal representation every transport (Telegram,
Discord, Web, CLI, REST) is normalised into, so the cognitive core never sees a
channel-specific structure. ``AgentResponse`` is the symmetric outbound contract.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MessageType(str, Enum):
    """Discriminator used by the Router to select a processing pipeline."""

    COMMAND = "command"
    TEXT = "text"
    PHOTO = "photo"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    UI = "ui"  # graphical-interface interaction
    CALLBACK = "callback"  # inline-button press
    UNKNOWN = "unknown"


class Attachment(BaseModel):
    """A binary attachment referenced by id/URL rather than inlined."""

    model_config = ConfigDict(frozen=True)

    kind: MessageType
    file_id: str
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


class UnifiedPayload(BaseModel):
    """Normalised inbound request. Immutable once built by the Gateway."""

    model_config = ConfigDict(frozen=True)

    channel: str = Field(description="Source transport, e.g. 'telegram' | 'cli'")
    external_user_id: str = Field(description="Stable user id within the channel")
    message_type: MessageType = MessageType.TEXT
    text: str = ""
    command: str | None = None  # populated when message_type == COMMAND
    attachments: tuple[Attachment, ...] = ()
    display_name: str | None = None
    language: str = "ru"
    metadata: dict[str, str] = Field(default_factory=dict)
    # Set by the sanitiser: raw text kept separate from the safe, model-facing text.
    raw_text: str = ""


class AgentResponse(BaseModel):
    """Normalised outbound reply the transport renders back to the user."""

    text: str
    attachments: tuple[Attachment, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)
