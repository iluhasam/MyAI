"""Telegram transport adapter (thin; aiogram is an optional dependency).

Maps aiogram updates to the Gateway's ``RawInbound`` and sends replies back.
Contains zero decision logic, so a breaking change in the Telegram API only ever
touches this file. Import of ``aiogram`` is deferred to construction time so the
rest of the platform runs without it installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.logger import get_logger
from app.gateway.gateway import Gateway, RawInbound

_log = get_logger(__name__)

# Progress-dot frames shown (with the native typing action) while the cognitive
# core works, so the user sees the bot is alive and busy.
_THINK_FRAMES = (
    "Думаю ●○○○○",
    "Думаю ●●○○○",
    "Думаю ●●●○○",
    "Думаю ●●●●○",
    "Думаю ●●●●●",
)
_ANIM_INTERVAL = 1.0  # seconds between frames (safe vs Telegram edit limits)


class TelegramAdapter:
    """Bridges aiogram <-> Gateway. Instantiate only when running the bot."""

    def __init__(self, gateway: Gateway, *, token: str, miniapp_url: str = "") -> None:
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
        self._miniapp_url = miniapp_url
        self._register_handlers()

    def _register_handlers(self) -> None:  # pragma: no cover - requires aiogram runtime
        from aiogram import types

        @self._dp.message()
        async def _on_message(message: "types.Message") -> None:
            raw = self._to_raw(message)
            # Commands are instant — no need for a thinking animation.
            if (message.text or "").startswith("/"):
                reply = await self._gateway.handle(raw)
                await self._safe_answer(message, reply.text, self._keyboard(reply))
                return

            # LLM turn: show an animated placeholder + typing action while working,
            # then morph the placeholder into the final answer.
            placeholder = await message.answer(_THINK_FRAMES[0])
            anim = asyncio.create_task(self._animate(message.chat.id, placeholder))
            try:
                reply = await self._gateway.handle(raw)
            finally:
                anim.cancel()
                await asyncio.gather(anim, return_exceptions=True)  # ensure it stopped
            await self._safe_edit(placeholder, reply.text, self._keyboard(reply))

        @self._dp.callback_query()
        async def _on_callback(callback: "types.CallbackQuery") -> None:
            # A button press re-enters the pipeline as the command "/{action}",
            # reusing every command handler; then we edit the message in place.
            reply = await self._gateway.handle(self._callback_raw(callback))
            await self._safe_edit(callback.message, reply.text, self._keyboard(reply))
            await callback.answer()

    # -- outbound rendering (Markdown-ish -> Telegram HTML, never fatal) ----
    @staticmethod
    def _render(text: str) -> str:
        """Turn **bold**/*italic* into Telegram HTML, escaping the rest.

        HTML-escape first so model output can't inject tags, then convert the
        emphasis markers. A lone/odd marker just stays literal — no parse error.
        """
        import html
        import re

        esc = html.escape(text, quote=False)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc, flags=re.S)
        esc = re.sub(r"\*(.+?)\*", r"<i>\1</i>", esc, flags=re.S)
        return esc

    async def _safe_answer(self, message: Any, text: str, reply_markup: Any = None) -> None:  # pragma: no cover - aiogram runtime
        """Send ``text`` as HTML; on any parse issue fall back to plain text."""
        from aiogram.exceptions import TelegramBadRequest

        try:
            await message.answer(self._render(text), reply_markup=reply_markup, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer(text, reply_markup=reply_markup)

    async def _safe_edit(self, msg: Any, text: str, reply_markup: Any = None) -> None:  # pragma: no cover - aiogram runtime
        """Edit ``msg`` to ``text`` as HTML; fall back to plain, then to a fresh send."""
        from aiogram.exceptions import TelegramBadRequest

        try:
            await msg.edit_text(self._render(text), reply_markup=reply_markup, parse_mode="HTML")
        except TelegramBadRequest:
            try:
                await msg.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest:
                await msg.answer(text, reply_markup=reply_markup)

    async def _animate(self, chat_id: int, placeholder: Any) -> None:  # pragma: no cover - aiogram runtime
        """Cycle the placeholder through 'thinking' frames + keep 'typing…' alive."""
        i = 1
        try:
            while True:
                try:
                    await self._bot.send_chat_action(chat_id, action="typing")
                except Exception:  # network hiccup — keep animating
                    pass
                await asyncio.sleep(_ANIM_INTERVAL)
                try:
                    await placeholder.edit_text(_THINK_FRAMES[i % len(_THINK_FRAMES)])
                except Exception:  # flood control / not modified — ignore
                    pass
                i += 1
        except asyncio.CancelledError:  # response is ready; stop cleanly
            pass

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

    async def _set_menu_button(self) -> None:  # pragma: no cover - requires aiogram runtime
        """Point the bot's menu button at the Mini App (if a valid URL is configured).

        Best-effort and never fatal: a bad/misconfigured URL only skips the button,
        it must not take down the bot (Telegram requires a https:// Web App URL).
        """
        url = self._miniapp_url.strip()
        if not url:
            return
        if not url.startswith("https://"):
            _log.warning("MINIAPP_URL must start with https:// — skipping menu button", extra={"url": url})
            return
        from aiogram.types import MenuButtonWebApp, WebAppInfo

        try:
            await self._bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="⚙️ Настройки", web_app=WebAppInfo(url=url))
            )
            _log.info("mini app menu button set", extra={"url": url})
        except Exception as exc:  # invalid URL / API hiccup — keep the bot running
            _log.warning("failed to set menu button; continuing", extra={"error": str(exc)})

    async def run(self) -> None:  # pragma: no cover - requires network + token
        """Start long-polling. Blocks until cancelled."""
        _log.info("starting Telegram long-polling")
        await self._set_commands()
        await self._set_menu_button()
        await self._dp.start_polling(self._bot)
