"""Model catalog: the set of models a user may switch between.

Maps short, human-friendly **aliases** (what the user types in ``/model <alias>``)
to concrete provider model strings. With OpenRouter one API key reaches many
providers, so every entry here is an ``openrouter/...`` route; swapping the
provider later means editing only this table, not the cognitive core.

The catalog is the single source of truth for *which* models exist and *which* is
the default — the per-user preference (stored in the DB) only ever holds an alias
validated against this table, so an unknown/removed model can never be selected.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One selectable model: its alias, provider route, and a short label."""

    alias: str
    model: str  # full provider string passed to the LLM client (e.g. LiteLLM)
    label: str  # human description shown by /models


# Curated default catalog. Aliases are intentionally short and memorable.
# Model ids verified against OpenRouter. Keep aliases stable; update the route
# string here if OpenRouter renames/retires a model.
_DEFAULT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo("gpt-4o-mini", "openrouter/openai/gpt-4o-mini", "OpenAI GPT-4o mini — быстрая и дешёвая"),
    ModelInfo("gpt-4o", "openrouter/openai/gpt-4o", "OpenAI GPT-4o — мощная, дороже"),
    ModelInfo("claude", "openrouter/anthropic/claude-sonnet-4", "Anthropic Claude Sonnet 4"),
    ModelInfo("gemini", "openrouter/google/gemini-2.5-flash", "Google Gemini 2.5 Flash — быстрая"),
    ModelInfo("llama", "openrouter/meta-llama/llama-3.1-8b-instruct", "Meta Llama 3.1 8B — дешёвая"),
    ModelInfo("deepseek", "openrouter/deepseek/deepseek-chat", "DeepSeek Chat — дешёвая, сильная"),
)


class ModelCatalog:
    """Immutable registry of selectable models keyed by alias."""

    def __init__(self, *, models: tuple[ModelInfo, ...] = _DEFAULT_MODELS, default_alias: str = "gpt-4o-mini") -> None:
        self._by_alias = {m.alias: m for m in models}
        if not self._by_alias:
            raise ValueError("model catalog cannot be empty")
        # Fall back to the first entry if the configured default is unknown.
        self._default_alias = default_alias if default_alias in self._by_alias else next(iter(self._by_alias))

    @property
    def default_alias(self) -> str:
        return self._default_alias

    def has(self, alias: str) -> bool:
        return alias in self._by_alias

    def resolve(self, alias: str | None) -> str:
        """Return the full provider model string for ``alias`` (or the default)."""
        info = self._by_alias.get(alias or self._default_alias)
        if info is None:
            info = self._by_alias[self._default_alias]
        return info.model

    def alias_or_default(self, alias: str | None) -> str:
        """Return ``alias`` if it is valid, else the catalog default."""
        return alias if alias and alias in self._by_alias else self._default_alias

    def list(self) -> list[ModelInfo]:
        """All models in registration order (for /models and the API)."""
        return list(self._by_alias.values())
