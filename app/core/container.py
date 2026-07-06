"""Declarative dependency-injection container (lightweight, stdlib-only).

Rather than pull in a third-party DI framework for the MVP, we implement a small
container that provides **lazy singletons**: heavy resources (database engine,
LLM client, memory backends) are constructed only on first access, which keeps
cold-start fast and memory low. Every dependency is overridable — call
``container.override(name, obj)`` in tests to inject mocks/fakes.

Wiring is done inside provider methods (not at import time) so the core package
never imports business/infra modules eagerly, avoiding import cycles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

from app.core.config import Settings, get_settings
from app.core.events import EventBus
from app.core.logger import get_logger

if TYPE_CHECKING:  # imported only for type hints; no runtime cost / cycles
    from app.agent.agent import Agent
    from app.database.database import Database
    from app.database.outbox_publisher import OutboxPublisher
    from app.gateway.gateway import Gateway
    from app.llm.base import LLMClient
    from app.memory.memory import MemorySubsystem
    from app.router.router import Router

_log = get_logger(__name__)
T = TypeVar("T")


class Container:
    """Application composition root holding lazily-built singletons."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._singletons: dict[str, Any] = {}
        self._overrides: dict[str, Any] = {}

    # -- generic lazy-singleton helper -------------------------------------
    def _get(self, key: str, factory: Callable[[], T]) -> T:
        if key in self._overrides:
            return self._overrides[key]
        if key not in self._singletons:
            _log.debug("constructing dependency", extra={"dependency": key})
            self._singletons[key] = factory()
        return self._singletons[key]

    def override(self, key: str, obj: Any) -> None:
        """Replace a dependency with ``obj`` (used by tests / alternate envs)."""
        self._overrides[key] = obj

    def reset_overrides(self) -> None:
        self._overrides.clear()

    # -- providers ----------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def event_bus(self) -> EventBus:
        return self._get("event_bus", EventBus)

    @property
    def database(self) -> "Database":
        def factory() -> "Database":
            from app.database.database import Database

            return Database(self._settings.database_url)

        return self._get("database", factory)

    @property
    def llm(self) -> "LLMClient":
        def factory() -> "LLMClient":
            from app.llm.factory import build_llm_client

            return build_llm_client(self._settings)

        return self._get("llm", factory)

    @property
    def memory(self) -> "MemorySubsystem":
        def factory() -> "MemorySubsystem":
            from app.memory.memory import MemorySubsystem

            return MemorySubsystem(
                database=self.database,
                llm=self.llm,
                session_window=self._settings.memory_session_window,
            )

        return self._get("memory", factory)

    @property
    def agent(self) -> "Agent":
        def factory() -> "Agent":
            from app.agent.agent import Agent
            from app.executor.executor import Executor
            from app.planner.planner import Planner
            from app.tools.manager import ToolManager

            tool_manager = ToolManager()
            tool_manager.register_defaults(llm=self.llm)
            return Agent(
                planner=Planner(llm=self.llm),
                executor=Executor(tool_manager=tool_manager, llm=self.llm),
                memory=self.memory,
            )

        return self._get("agent", factory)

    @property
    def router(self) -> "Router":
        def factory() -> "Router":
            from app.router.router import Router

            return Router(agent=self.agent)

        return self._get("router", factory)

    @property
    def gateway(self) -> "Gateway":
        def factory() -> "Gateway":
            from app.gateway.gateway import Gateway

            return Gateway(router=self.router)

        return self._get("gateway", factory)

    @property
    def outbox_publisher(self) -> "OutboxPublisher":
        def factory() -> "OutboxPublisher":
            from app.database.outbox_publisher import OutboxPublisher

            return OutboxPublisher(
                self.database,
                self.event_bus,
                interval=self._settings.outbox_poll_interval,
                max_attempts=self._settings.outbox_max_attempts,
            )

        return self._get("outbox_publisher", factory)
