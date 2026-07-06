"""Custom exception hierarchy for the platform.

A single root (``PlatformError``) lets the outermost handlers catch every
domain error while still allowing precise ``except`` clauses in the layers that
know how to recover. Transport layers translate these into user-facing messages
without leaking internal detail (important for prompt/system-leak safety).
"""

from __future__ import annotations


class PlatformError(Exception):
    """Base class for all deliberate, application-level errors."""

    #: Safe message shown to end users; subclasses may override.
    user_message: str = "Внутренняя ошибка. Попробуйте позже."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.__class__.__name__)
        if user_message is not None:
            self.user_message = user_message


class ConfigurationError(PlatformError):
    """Invalid or missing configuration detected at startup."""

    user_message = "Сервис временно недоступен (ошибка конфигурации)."


class ValidationError(PlatformError):
    """Incoming payload failed validation or sanitisation."""

    user_message = "Не удалось обработать запрос: некорректные данные."


class AgentError(PlatformError):
    """Failure inside the cognitive core (planner/executor/agent)."""

    user_message = "Агент не смог обработать запрос."


class LLMError(PlatformError):
    """Language-model call failed after retries/fallbacks were exhausted."""

    user_message = "Модель временно недоступна. Повторите попытку позже."


class ToolError(PlatformError):
    """A tool invocation failed during plan execution."""

    user_message = "Не удалось выполнить один из шагов запроса."
