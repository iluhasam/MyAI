"""Router: pick a pipeline based on message type, then hand off to the Agent.

The Router is a thin classifier/dispatcher. Each ``MessageType`` maps to a
coroutine pipeline. For the MVP vertical slice, text/command/callback flow into
the cognitive core; media types return an honest "not yet enabled" reply that a
later iteration (Vision/Speech/OCR modules) will replace — no silent failures.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from app.core.logger import get_logger
from app.gateway.payload import AgentResponse, MessageType, UnifiedPayload

_log = get_logger(__name__)


class AgentPort(Protocol):
    """Structural interface the Router needs from the cognitive core."""

    async def process(self, payload: UnifiedPayload) -> AgentResponse: ...


Pipeline = Callable[[UnifiedPayload], Awaitable[AgentResponse]]


class Router:
    """Classifies payloads and routes them to the correct async pipeline."""

    def __init__(self, agent: AgentPort) -> None:
        self._agent = agent
        # Registry keeps dispatch O(1) and makes adding pipelines declarative.
        self._pipelines: dict[MessageType, Pipeline] = {
            MessageType.TEXT: self._agent.process,
            MessageType.COMMAND: self._handle_command,
            MessageType.CALLBACK: self._agent.process,
            MessageType.PHOTO: self._not_enabled("обработка изображений"),
            MessageType.VOICE: self._not_enabled("распознавание речи"),
            MessageType.VIDEO_NOTE: self._not_enabled("обработка видео"),
            MessageType.DOCUMENT: self._not_enabled("разбор документов"),
        }

    async def dispatch(self, payload: UnifiedPayload) -> AgentResponse:
        pipeline = self._pipelines.get(payload.message_type, self._fallback)
        _log.debug("routing", extra={"type": payload.message_type.value})
        return await pipeline(payload)

    # -- pipelines ----------------------------------------------------------
    async def _handle_command(self, payload: UnifiedPayload) -> AgentResponse:
        """Handle built-in slash commands; unknown commands go to the agent."""
        if payload.command in {"start", "help"}:
            return AgentResponse(
                text=(
                    "Привет! Я персональный ИИ-агент. Напиши сообщение — и я отвечу.\n\n"
                    "Команды:\n"
                    "• /status — текущая модель и стиль\n"
                    "• /models, /model <название> — выбрать модель\n"
                    "• /personas, /persona <название> — выбрать стиль общения\n"
                    "• /reset — очистить историю разговора\n\n"
                    "Медиа (фото, голос, документы) появятся в следующих итерациях."
                )
            )
        return await self._agent.process(payload)

    async def _fallback(self, payload: UnifiedPayload) -> AgentResponse:
        return AgentResponse(text="Не понял тип сообщения. Пришлите текст, пожалуйста.")

    @staticmethod
    def _not_enabled(feature: str) -> Pipeline:
        async def _pipeline(_: UnifiedPayload) -> AgentResponse:
            return AgentResponse(text=f"Функция «{feature}» ещё не подключена в этой сборке.")

        return _pipeline
