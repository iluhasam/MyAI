"""Planner: strategic decomposition of a request into an ExecutionPlan.

The planner *decides* but never *acts*: it inspects the sanitised request plus
memory context and emits an ordered plan of tool steps followed by a final
LLM synthesis. This MVP uses lightweight heuristics (a deterministic stand-in
for a Chain-of-Thought / ReAct LLM planner) so the pipeline runs offline; the
:class:`ExecutionPlan` shape is exactly what a model-driven planner would fill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.gateway.payload import UnifiedPayload
from app.memory.memory import MemoryContext

# Detects a self-contained arithmetic expression (digits + operators).
_ARITHMETIC = re.compile(r"^[\s\d.()+\-*/%^]+$")
_HAS_OP = re.compile(r"[+\-*/%^]")


@dataclass(slots=True, frozen=True)
class PlanStep:
    """One node in the execution graph: call ``tool`` with ``arguments``."""

    tool: str
    arguments: dict[str, Any]
    description: str


@dataclass(slots=True)
class ExecutionPlan:
    """Ordered tool steps + a flag for the final LLM synthesis step."""

    steps: list[PlanStep] = field(default_factory=list)
    synthesise_with_llm: bool = True
    rationale: str = ""


class Planner:
    """Produces an :class:`ExecutionPlan` from a request and its context."""

    def __init__(self, llm: object | None = None) -> None:
        # llm reserved for a future model-driven planner; unused in the heuristic MVP.
        self._llm = llm

    def plan(self, payload: UnifiedPayload, context: MemoryContext) -> ExecutionPlan:
        text = payload.text.strip()
        steps: list[PlanStep] = []

        expression = self._extract_arithmetic(text)
        if expression is not None:
            steps.append(
                PlanStep(
                    tool="calculator",
                    arguments={"expression": expression},
                    description="Вычислить арифметическое выражение из запроса.",
                )
            )

        rationale = (
            "Обнаружено арифметическое выражение — вычисляем инструментом, затем синтез ответа."
            if steps
            else "Инструменты не требуются — прямой ответ модели с учётом контекста памяти."
        )
        return ExecutionPlan(steps=steps, synthesise_with_llm=True, rationale=rationale)

    @staticmethod
    def _extract_arithmetic(text: str) -> str | None:
        """Return a pure arithmetic expression if the message is one, else None."""
        candidate = text.rstrip("=? ").strip()
        if candidate and _ARITHMETIC.match(candidate) and _HAS_OP.search(candidate):
            return candidate
        return None
