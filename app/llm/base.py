"""LLM interface contract + safe prompt-assembly helpers.

``LLMClient`` is a ``typing.Protocol`` (structural typing) so the cognitive core
depends only on the method signatures, never a concrete provider — mocks and real
clients are interchangeable. ``wrap_user_input`` enforces the security rule that
untrusted user text is always fenced inside explicit delimiters and never
concatenated raw into system instructions.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """One message in a chat completion request."""

    role: Role
    content: str


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic async LLM surface used throughout the platform."""

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> str:
        """Return a text completion. ``model`` overrides the client default per call."""
        ...

    async def vision(self, prompt: str, *, image_url: str) -> str:
        """Return a textual description/answer for an image + prompt."""

    async def embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        """Return an embedding vector per input text."""


def wrap_user_input(text: str) -> str:
    """Fence untrusted user text in delimiters to resist prompt injection.

    Any stray closing tag inside the user text is neutralised so it cannot break
    out of the fence and inject instructions into the surrounding prompt.
    """
    safe = text.replace("</user_input>", "<\\/user_input>")
    return f"<user_input>\n{safe}\n</user_input>"
