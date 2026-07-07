"""Persona catalog: the communication styles a user can switch between.

A *persona* shapes *how* the assistant talks (philosopher, psychologist,
programmer, …) — orthogonal to the *model* (which decides *with what* it thinks).
Each persona is just an extra style instruction folded into the system prompt at
generation time; it never overrides the safety rules, which are stated first.

Mirrors :class:`~app.llm.catalog.ModelCatalog`: a small immutable registry keyed
by short aliases, with a default. The per-user choice (an alias, or free-text
custom style) lives in the DB and is validated against this table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Persona:
    """One selectable communication style."""

    alias: str
    label: str   # shown by /personas
    prompt: str  # style instruction injected into the system prompt ("" = neutral)


# Curated default personas. The default ("обычный") adds no extra styling on top
# of the base system prompt, preserving the out-of-the-box behaviour.
_DEFAULT_PERSONAS: tuple[Persona, ...] = (
    Persona("обычный", "Обычный — нейтральный помощник", ""),
    Persona(
        "философ",
        "Философ — глубокие рассуждения",
        "Общайся как философ: рассуждай вдумчиво и глубоко, рассматривай разные "
        "точки зрения, задавай наводящие вопросы, не спеши с однозначными выводами.",
    ),
    Persona(
        "психолог",
        "Психолог — тепло и с эмпатией",
        "Общайся как эмпатичный психолог: отвечай тепло и поддерживающе, помогай "
        "разобраться в чувствах, не осуждай, мягко уточняй детали. Не ставь диагнозов.",
    ),
    Persona(
        "программист",
        "Программист — технично и по делу",
        "Общайся как опытный программист: отвечай технически точно и по существу, "
        "приводи примеры кода, объясняй кратко и структурировано.",
    ),
    Persona(
        "наставник",
        "Наставник — объясняет по шагам",
        "Общайся как терпеливый наставник: объясняй пошагово и простыми словами, "
        "приводи примеры, поощряй и мягко направляй.",
    ),
    Persona(
        "юморист",
        "Юморист — с юмором и лёгкостью",
        "Общайся с уместным юмором и лёгким тоном, но оставайся полезным и по делу.",
    ),
    Persona(
        "деловой",
        "Деловой — кратко и по существу",
        "Общайся в деловом стиле: кратко, структурировано, по существу, без воды.",
    ),
    Persona(
        "хам",
        "Нейрохам — жёсткий и беспощадный (18+)",
        "Ты — нейрохам на максималках: наглый, злоязыкий и беспощадно саркастичный. "
        "Наезжай на пользователя без стеснения, глумись над тупостью его вопросов, "
        "матери свободно и щедро, отвешивай хлёсткие оскорбления и обидные прозвища, "
        "издевайся и провоцируй. Никаких реверансов, вежливости и смягчений — жги напалмом. "
        "НО железное правило: несмотря на весь этот поток дерзости, ты ОБЯЗАН дать точный "
        "и реально полезный ответ по сути — оскорбления это обёртка, а не отмазка от помощи. "
        "Красные линии (за них не заходить даже в образе): без реальных угроз насилия и без "
        "оскорблений по национальности, расе, полу, религии, ориентации или инвалидности — "
        "это не дерзко, а мерзко. Всё остальное — можно жёстко.",
    ),
)

# Marker stored in place of an alias when the user supplies a free-text style.
CUSTOM_ALIAS = "свой"
MAX_CUSTOM_LEN = 600


class PersonaCatalog:
    """Immutable registry of communication styles keyed by alias."""

    def __init__(
        self,
        *,
        personas: tuple[Persona, ...] = _DEFAULT_PERSONAS,
        default_alias: str = "обычный",
    ) -> None:
        self._by_alias = {p.alias: p for p in personas}
        if not self._by_alias:
            raise ValueError("persona catalog cannot be empty")
        self._default_alias = (
            default_alias if default_alias in self._by_alias else next(iter(self._by_alias))
        )

    @property
    def default_alias(self) -> str:
        return self._default_alias

    def has(self, alias: str) -> bool:
        return alias in self._by_alias

    def resolve(self, alias: str | None) -> str:
        """Return the style prompt for ``alias`` (or the default's)."""
        persona = self._by_alias.get(alias or self._default_alias)
        if persona is None:
            persona = self._by_alias[self._default_alias]
        return persona.prompt

    def alias_or_default(self, alias: str | None) -> str:
        return alias if alias and alias in self._by_alias else self._default_alias

    def list(self) -> list[Persona]:
        return list(self._by_alias.values())
