"""Agent: coordinates one full cognitive turn.

Flow: load consolidated memory context -> ask the Planner for a plan -> have the
Executor run it and synthesise a reply -> persist the turn to memory -> emit a
domain event. Errors are converted into a safe user-facing response so a single
failed turn never crashes the transport.
"""

from __future__ import annotations

from app.core.exceptions import PlatformError
from app.core.logger import get_logger
from app.executor.executor import Executor
from app.gateway.payload import AgentResponse, UnifiedPayload
from app.llm.catalog import ModelCatalog
from app.memory.memory import MemorySubsystem
from app.persona import CUSTOM_ALIAS, MAX_CUSTOM_LEN, PersonaCatalog
from app.planner.planner import Planner

_log = get_logger(__name__)


class Agent:
    """The cognitive core's orchestrator (the 'brain' coordinating the cycle)."""

    def __init__(
        self,
        *,
        planner: Planner,
        executor: Executor,
        memory: MemorySubsystem,
        catalog: ModelCatalog,
        personas: PersonaCatalog,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._memory = memory
        self._catalog = catalog
        self._personas = personas

    async def process(self, payload: UnifiedPayload) -> AgentResponse:
        """Run one cognitive turn and return the reply."""
        # Model-selection commands are handled here (they need user + DB access)
        # and short-circuit the cognitive cycle.
        if payload.command == "models":
            return await self._list_models(payload)
        if payload.command == "model":
            return await self._select_model(payload)
        if payload.command == "personas":
            return await self._list_personas(payload)
        if payload.command == "persona":
            return await self._select_persona(payload)
        if payload.command == "status":
            return await self._status(payload)
        if payload.command == "reset":
            return await self._reset(payload)
        try:
            context = await self._memory.load(payload)
            plan = self._planner.plan(payload, context)
            _log.debug("plan ready", extra={"steps": len(plan.steps), "why": plan.rationale})

            answer = await self._executor.execute(plan, payload, context)
            # record_turn persists the turn AND enqueues the ``message.answered``
            # event in one transaction; the OutboxPublisher relays it to the bus.
            await self._memory.record_turn(
                context,
                user_text=payload.text,
                assistant_text=answer,
                channel=payload.channel,
            )
            return AgentResponse(text=answer)
        except PlatformError as exc:
            _log.warning("cognitive turn failed", extra={"error": str(exc)})
            return AgentResponse(text=exc.user_message)
        except Exception:  # last-resort guard: never leak internals to the user
            _log.exception("unexpected error in cognitive turn")
            return AgentResponse(text="Произошла непредвиденная ошибка. Попробуйте ещё раз.")

    # -- model-selection commands ------------------------------------------
    async def _list_models(self, payload: UnifiedPayload) -> AgentResponse:
        """`/models` — show the catalog and mark the user's current choice."""
        current = await self._memory.get_preferred_alias(payload)
        lines = ["Доступные модели (выбрать: /model <название>):"]
        for info in self._catalog.list():
            mark = " ← сейчас" if info.alias == current else ""
            lines.append(f"• {info.alias} — {info.label}{mark}")
        return AgentResponse(text="\n".join(lines), metadata={"current_model": current})

    async def _select_model(self, payload: UnifiedPayload) -> AgentResponse:
        """`/model <alias>` — validate and persist the user's model choice."""
        parts = payload.text.split()
        alias = parts[1] if len(parts) >= 2 else ""
        if not alias:
            current = await self._memory.get_preferred_alias(payload)
            return AgentResponse(
                text=(
                    f"Сейчас выбрана модель: {current}. "
                    "Чтобы сменить — /model <название>, список — /models."
                )
            )
        if not self._catalog.has(alias):
            valid = ", ".join(info.alias for info in self._catalog.list())
            return AgentResponse(
                text=f"Неизвестная модель «{alias}». Доступные: {valid}. Список — /models."
            )
        await self._memory.set_preferred_model(payload, alias)
        return AgentResponse(
            text=f"Готово — теперь отвечаю через «{alias}».",
            metadata={"current_model": alias},
        )

    # -- status / reset ----------------------------------------------------
    async def _status(self, payload: UnifiedPayload) -> AgentResponse:
        """`/status` — show the user's current model and persona."""
        model = await self._memory.get_preferred_alias(payload)
        persona = await self._memory.get_persona_alias(payload)
        return AgentResponse(
            text=(
                f"Текущие настройки:\n"
                f"• Модель: {model}  (сменить — /model, список — /models)\n"
                f"• Стиль: {persona}  (сменить — /persona, список — /personas)"
            ),
            metadata={"current_model": model, "current_persona": persona},
        )

    async def _reset(self, payload: UnifiedPayload) -> AgentResponse:
        """`/reset` — forget the conversation (settings are kept)."""
        await self._memory.reset(payload)
        return AgentResponse(
            text="История разговора очищена — начинаем с чистого листа. "
            "Выбранные модель и стиль сохранены."
        )

    # -- persona-selection commands ----------------------------------------
    async def _list_personas(self, payload: UnifiedPayload) -> AgentResponse:
        """`/personas` — show the persona catalog and mark the current choice."""
        current = await self._memory.get_persona_alias(payload)
        lines = ["Стили общения (выбрать: /persona <название>):"]
        for p in self._personas.list():
            mark = " ← сейчас" if p.alias == current else ""
            lines.append(f"• {p.alias} — {p.label}{mark}")
        lines.append(f"• {CUSTOM_ALIAS} <текст> — свой стиль" + (" ← сейчас" if current == CUSTOM_ALIAS else ""))
        return AgentResponse(text="\n".join(lines), metadata={"current_persona": current})

    async def _select_persona(self, payload: UnifiedPayload) -> AgentResponse:
        """`/persona <alias>` or `/persona свой <текст>` — set the communication style."""
        parts = payload.text.split()
        alias = parts[1] if len(parts) >= 2 else ""
        if not alias:
            current = await self._memory.get_persona_alias(payload)
            return AgentResponse(
                text=(
                    f"Сейчас стиль: {current}. Сменить — /persona <название>, "
                    "свой стиль — /persona свой <текст>, список — /personas."
                )
            )
        if alias == CUSTOM_ALIAS:
            custom = payload.text.split(maxsplit=2)[2].strip() if len(parts) >= 3 else ""
            if not custom:
                return AgentResponse(
                    text="Опиши свой стиль после команды, например: /persona свой Ты — саркастичный кот."
                )
            custom = custom[:MAX_CUSTOM_LEN]
            await self._memory.set_persona(payload, alias=None, custom=custom)
            return AgentResponse(
                text="Готово — теперь общаюсь в твоём стиле.",
                metadata={"current_persona": CUSTOM_ALIAS},
            )
        if not self._personas.has(alias):
            valid = ", ".join(p.alias for p in self._personas.list())
            return AgentResponse(
                text=f"Неизвестный стиль «{alias}». Доступные: {valid}, или {CUSTOM_ALIAS} <текст>. Список — /personas."
            )
        await self._memory.set_persona(payload, alias=alias, custom=None)
        return AgentResponse(
            text=f"Готово — теперь общаюсь в стиле «{alias}».",
            metadata={"current_persona": alias},
        )
