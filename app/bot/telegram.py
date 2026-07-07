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
            await message.answer(reply.text, reply_markup=self._keyboard(reply))

        @self._dp.callback_query()
        async def _on_callback(callback: "types.CallbackQuery") -> None:
            # A button press re-enters the pipeline as the command "/{action}",
            # reusing every command handler; then we edit the message in place.
            reply = await self._gateway.handle(self._callback_raw(callback))
            kb = self._keyboard(reply)
            try:
                await callback.message.edit_text(reply.text, reply_markup=kb)
            except Exception:  # e.g. "message is not modified" / too old
                await callback.message.answer(reply.text, reply_markup=kb)
            await callback.answer()

    def _keyboard(self, response: Any):  # pragma: no cover - requires aiogram runtime
        """Render an AgentResponse's buttons as a Telegram inline keyboard."""
        if not response.buttons:
            return None
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=b.label, callback_data=b.action) for b in row]
                for row in response.buttons
            ]
        )

    @staticmethod
    def _callback_raw(callback: Any) -> RawInbound:
        data = callback.data or ""
        user = callback.from_user
        return {
            "channel": "telegram",
            "external_user_id": str(user.id),
            "message_type": "command",
            "text": "/" + data,
            "command": data.split()[0] if data else "",
            "display_name": user.full_name,
            "language": user.language_code or "ru",
        }

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

    async def _set_commands(self) -> None:  # pragma: no cover - requires aiogram runtime
        """Register the slash-command menu shown when the user types '/'."""
        from aiogram.types import BotCommand

        await self._bot.set_my_commands(
            [
                BotCommand(command="menu", description="Меню настроек (кнопки)"),
                BotCommand(command="status", description="Текущая модель и стиль"),
                BotCommand(command="models", description="Список моделей"),
                BotCommand(command="model", description="Выбрать модель: /model <название>"),
                BotCommand(command="personas", description="Список стилей общения"),
                BotCommand(command="persona", description="Выбрать стиль: /persona <название>"),
                BotCommand(command="reset", description="Очистить историю разговора"),
                BotCommand(command="help", description="Справка"),
            ]
        )

    async def run(self) -> None:  # pragma: no cover - requires network + token
        """Start long-polling. Blocks until cancelled."""
        _log.info("starting Telegram long-polling")
        await self._set_commands()
        await self._dp.start_polling(self._bot)
