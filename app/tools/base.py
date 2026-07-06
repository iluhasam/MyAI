"""Tool contract.

Tools use an ``abc.ABC`` base (not a Protocol) because we want shared default
behaviour — JSON-schema validation and uniform error wrapping — inherited by
every concrete tool, matching the guidance that ABCs fit pipelines needing base
logic while Protocols fit pure structural interfaces (used elsewhere for the LLM).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ToolError


@dataclass(slots=True, frozen=True)
class ToolResult:
    """Uniform result envelope returned by every tool invocation."""

    tool: str
    ok: bool
    output: str
    data: dict[str, Any] | None = None


class Tool(abc.ABC):
    """Abstract base for all tools registered with the :class:`ToolManager`."""

    #: Unique tool name referenced by planner steps and the LLM tool spec.
    name: str
    #: Human/LLM-readable description of what the tool does.
    description: str
    #: JSON-schema of the tool's ``arguments`` object (for validation + LLM spec).
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        """Validate arguments then run the tool, wrapping failures uniformly."""
        try:
            self._validate(arguments)
            return await self.run(arguments)
        except ToolError:
            raise
        except Exception as exc:  # convert any tool bug into a controlled error
            raise ToolError(f"tool {self.name!r} failed: {exc}") from exc

    @abc.abstractmethod
    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool. Subclasses implement the real work here."""
        raise NotImplementedError

    def spec(self) -> dict[str, Any]:
        """Return the structured metadata injected into the LLM system prompt."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def _validate(self, arguments: dict[str, Any]) -> None:
        """Minimal required-key check (kept dependency-free for the MVP)."""
        required = self.parameters.get("required", [])
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ToolError(f"tool {self.name!r} missing arguments: {missing}")
