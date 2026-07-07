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

# Heuristic intent for a web lookup: explicit search verbs, "where to get" phrases,
# recency words, or a raw URL. A model-driven planner would decide this itself.
_SEARCH_INTENT = re.compile(
    r"ссылк|найд[иё]|поищ|загугл|погугл|гугл|в интернете|в сети|источник|"
    r"где (?:взять|скачать|найти|можно|посмотреть|купить)|"
    r"актуальн|свеж|последн|новост|что нового|https?://",
    re.IGNORECASE,
)


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
            rationale = "Арифметическое выражение — вычисляем инструментом, затем синтез ответа."
        elif text and _SEARCH_INTENT.search(text):
            steps.append(
                PlanStep(
                    tool="web_search",
                    arguments={"query": text},
                    description="Поиск в интернете для актуальной информации и ссылок.",
                )
            )
            rationale = "Запрос требует свежих данных/ссылок — ищем в интернете, затем синтез ответа."
        else:
            rationale = "Инструменты не требуются — прямой ответ модели с учётом контекста памяти."

        return ExecutionPlan(steps=steps, synthesise_with_llm=True, rationale=rationale)

    @staticmethod
    def _extract_arithmetic(text: str) -> str | None:
        """Return a pure arithmetic expression if the message is one, else None."""
        candidate = text.rstrip("=? ").strip()
        if candidate and _ARITHMETIC.match(candidate) and _HAS_OP.search(candidate):
            return candidate
        return None
