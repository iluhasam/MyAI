"""Gateway: adapt any transport's raw event into a sanitised UnifiedPayload.

Transports hand the Gateway a plain dict (``RawInbound``) describing the event.
The Gateway validates/normalises it, runs sanitisation, and forwards a frozen
``UnifiedPayload`` to the Router — returning the Router's ``AgentResponse``.
It contains no decision logic of its own beyond normalisation & safety.
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from app.core.logger import get_logger
from app.gateway.payload import Attachment, MessageType, UnifiedPayload
from app.gateway.sanitizer import sanitize_text

_log = get_logger(__name__)


class RawInbound(TypedDict, total=False):
    """Loosely-typed inbound dict produced by a transport adapter."""

    channel: str
    external_user_id: str
    message_type: str
    text: str
    command: str
    display_name: str
    language: str
    attachments: list[dict[str, object]]
    metadata: dict[str, str]


class RouterPort(Protocol):
    """Structural interface the Gateway needs from the Router (duck typing)."""

    async def dispatch(self, payload: UnifiedPayload): ...


class Gateway:
    """Normalisation + sanitisation boundary between transports and the core."""

    def __init__(self, router: RouterPort) -> None:
        self._router = router

    async def handle(self, raw: RawInbound):
        """Normalise ``raw``, sanitise it, and dispatch through the Router."""
        payload = self._normalise(raw)
        _log.info(
            "inbound normalised",
            extra={
                "channel": payload.channel,
                "type": payload.message_type.value,
                "user": payload.external_user_id,
            },
        )
        return await self._router.dispatch(payload)

    # -- normalisation ------------------------------------------------------
    def _normalise(self, raw: RawInbound) -> UnifiedPayload:
        raw_text = str(raw.get("text", ""))
        result = sanitize_text(raw_text)

        msg_type = self._coerce_type(raw.get("message_type"), text=result.text)
        command = raw.get("command")
        if msg_type is MessageType.COMMAND and command is None and result.text.startswith("/"):
            command = result.text.split()[0].lstrip("/")

        metadata: dict[str, str] = dict(raw.get("metadata", {}))
        if result.injection_suspected:
            metadata["injection_suspected"] = "true"
        if result.pii_redacted:
            metadata["pii_redacted"] = "true"

        attachments = tuple(
            Attachment(
                kind=self._coerce_type(a.get("kind"), text=""),
                file_id=str(a.get("file_id", "")),
                filename=a.get("filename"),  # type: ignore[arg-type]
                mime_type=a.get("mime_type"),  # type: ignore[arg-type]
                size_bytes=a.get("size_bytes"),  # type: ignore[arg-type]
            )
            for a in raw.get("attachments", [])
        )

        return UnifiedPayload(
            channel=str(raw.get("channel", "unknown")),
            external_user_id=str(raw.get("external_user_id", "anonymous")),
            message_type=msg_type,
            text=result.text,
            raw_text=raw_text,
            command=command,
            attachments=attachments,
            display_name=raw.get("display_name"),
            language=str(raw.get("language", "ru")),
            metadata=metadata,
        )

    @staticmethod
    def _coerce_type(value: object, *, text: str) -> MessageType:
        """Map a transport type string to MessageType, inferring commands from '/'."""
        if isinstance(value, str):
            try:
                return MessageType(value)
            except ValueError:
                pass
        if text.startswith("/"):
            return MessageType.COMMAND
        return MessageType.TEXT if text else MessageType.UNKNOWN
