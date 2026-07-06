"""ToolManager: single registry of tools available to the agent.

Handles registration (with duplicate/name-schema validation), exposes the
aggregated JSON tool specification injected into the LLM system prompt, and
routes validated calls to the right tool. Only registered tools are callable,
which blocks invocation of undocumented functions (a prompt-injection safeguard).
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ToolError
from app.core.logger import get_logger
from app.llm.base import LLMClient
from app.tools.base import Tool, ToolResult
from app.tools.calculator import CalculatorTool

_log = get_logger(__name__)


class ToolManager:
    """Registry + dispatcher for tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not getattr(tool, "name", None):
            raise ToolError("tool must define a non-empty 'name'")
        if tool.name in self._tools:
            raise ToolError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool
        _log.debug("tool registered", extra={"tool": tool.name})

    def register_defaults(self, *, llm: LLMClient | None = None) -> None:
        """Register the built-in tool set shipped with the MVP."""
        self.register(CalculatorTool())
        # Future built-ins (Vision/OCR/Search/Parser) register here as they land,
        # optionally using the provided llm client.

    def has(self, name: str) -> bool:
        return name in self._tools

    def specs(self) -> list[dict[str, Any]]:
        """Structured metadata for every tool (declared to the LLM)."""
        return [tool.spec() for tool in self._tools.values()]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool {name!r}")
        return await tool.invoke(arguments)
