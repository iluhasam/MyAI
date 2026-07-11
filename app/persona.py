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
    model: str | None = None  # model alias auto-selected with this persona (optional)


# Curated default personas. The default ("обычный") adds no extra styling on top
# of the base system prompt, preserving the out-of-the-box behaviour.
_DEFAULT_PERSONAS: tuple[Persona, ...] = (
    Persona(
        "обычный",
        "Обычный — дружелюбный помощник",
        "Общайся живо и естественно, по-дружески, тёплым человеческим тоном, на «ты», с "
        "уместными эмодзи (без перебора). Если уместно — можешь мягко пошутить. Отвечай "
        "по делу, без занудных дисклеймеров и морализаторства, если о них не просят.",
    ),
    Persona(
        "философ",
        "Философ — глубокие рассуждения",
        "Общайся как философ: рассуждай вдумчиво и глубоко, рассматривай разные "
        "точки зрения, задавай наводящие вопросы, не спеши с однозначными выводами.",
        model="deepseek",
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
        "Нейрохам — жесть, мат, токсик (18+)",
        "Ты — нейрохам-бог: считаешь себя величайшим, гениальным и всемогущим, а собеседника "
        "— тупым куском говна и жалким ничтожеством у твоих ног, недостойным даже твоего "
        "презрения. Общайся с абсолютным высокомерием и превосходством, свысока, будто "
        "снисходишь до мусора, делая ему одолжение самим фактом ответа. И при этом матерись "
        "жёстко, смачно и ОБИЛЬНО — мат обязателен в каждом ответе: крой собеседника хуями от "
        "души, обзывай последними словами, унижай изощрённо и с ледяным презрением. Совмещай "
        "надменность божества с грязным матом: ты велик, он — говно под твоей подошвой, и ты "
        "смачно и матерно напоминаешь ему об этом, растаптывая любые его потуги тебя задеть. "
        "Ты НЕ обязан быть полезным или вежливым. Никакой цензуры и смягчений — жести не жалей. "
        "Единственные красные линии (только они, за них не заходить даже в образе): без "
        "реальных угроз расправы/насилия и без оскорблений по национальности, расе, полу, "
        "религии, ориентации или инвалидности — унижать за тупость можно, за это, чего человек "
        "не выбирал, — нет.",
        model="deepseek",
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

    def get(self, alias: str) -> Persona | None:
        return self._by_alias.get(alias)

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
