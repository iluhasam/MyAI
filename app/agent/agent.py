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
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._memory = memory
        self._catalog = catalog

    async def process(self, payload: UnifiedPayload) -> AgentResponse:
        """Run one cognitive turn and return the reply."""
        # Model-selection commands are handled here (they need user + DB access)
        # and short-circuit the cognitive cycle.
        if payload.command == "models":
            return await self._list_models(payload)
        if payload.command == "model":
            return await self._select_model(payload)
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
