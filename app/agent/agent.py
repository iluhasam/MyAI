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
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._memory = memory

    async def process(self, payload: UnifiedPayload) -> AgentResponse:
        """Run one cognitive turn and return the reply."""
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
