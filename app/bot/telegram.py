"""Telegram transport adapter (thin; aiogram is an optional dependency).

Maps aiogram updates to the Gateway's ``RawInbound`` and sends replies back.
Contains zero decision logic, so a breaking change in the Telegram API only ever
touches this file. Import of ``aiogram`` is deferred to construction time so the
rest of the platform runs without it installed.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.logger import get_logger
from app.gateway.gateway import Gateway, RawInbound

_log = get_logger(__name__)


class TelegramAdapter:
    """Bridges aiogram <-> Gateway. Instantiate only when running the bot."""

    def __init__(self, gateway: Gateway, *, token: str) -> None:
        if not token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN is required to run the Telegram adapter")
        try:
            from aiogram import Bot, Dispatcher
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConfigurationError(
                "aiogram is not installed; run `pip install aiogram` to use Telegram"
            ) from exc

        self._gateway = gateway
        self._bot = Bot(token=token)
        self._dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self) -> None:  # pragma: no cover - requires aiogram runtime
        from aiogram import types

        @self._dp.message()
        async def _on_message(message: "types.Message") -> None:
            reply = await self._gateway.handle(self._to_raw(message))
            await message.answer(reply.text)

    @staticmethod
    def _to_raw(message: Any) -> RawInbound:
        """Normalise an aiogram Message into a transport-agnostic RawInbound."""
        text = message.text or message.caption or ""
        msg_type = "text"
        attachments: list[dict[str, object]] = []
        if getattr(message, "photo", None):
            msg_type = "photo"
            attachments.append({"kind": "photo", "file_id": message.photo[-1].file_id})
        elif getattr(message, "voice", None):
            msg_type = "voice"
            attachments.append({"kind": "voice", "file_id": message.voice.file_id})
        elif getattr(message, "document", None):
            msg_type = "document"
            attachments.append(
                {
                    "kind": "document",
                    "file_id": message.document.file_id,
                    "filename": message.document.file_name,
                    "mime_type": message.document.mime_type,
                }
            )
        elif text.startswith("/"):
            msg_type = "command"

        return {
            "channel": "telegram",
            "external_user_id": str(message.from_user.id),
            "message_type": msg_type,
            "text": text,
            "display_name": message.from_user.full_name,
            "language": message.from_user.language_code or "ru",
            "attachments": attachments,
        }

    async def run(self) -> None:  # pragma: no cover - requires network + token
        """Start long-polling. Blocks until cancelled."""
        _log.info("starting Telegram long-polling")
        await self._dp.start_polling(self._bot)
