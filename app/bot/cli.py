"""CLI transport adapter — a real, minimal channel used for local runs & tests.

Proves the platform is channel-agnostic: the exact same Gateway/Router/Agent
stack serves a terminal session with no Telegram dependency. Reads lines from an
async-friendly loop and prints the agent's replies.
"""

from __future__ import annotations

import asyncio

from app.core.logger import get_logger
from app.gateway.gateway import Gateway, RawInbound

_log = get_logger(__name__)


class CLIAdapter:
    """Drives the platform from stdin/stdout (or a supplied script of lines)."""

    def __init__(self, gateway: Gateway, *, user_id: str = "cli-user") -> None:
        self._gateway = gateway
        self._user_id = user_id

    def _raw(self, text: str) -> RawInbound:
        return {
            "channel": "cli",
            "external_user_id": self._user_id,
            "message_type": "command" if text.startswith("/") else "text",
            "text": text,
            "display_name": "CLI User",
            "language": "ru",
        }

    async def send(self, text: str) -> str:
        """Send one message through the pipeline and return the reply text."""
        response = await self._gateway.handle(self._raw(text))
        return response.text

    async def run(self) -> None:  # pragma: no cover - interactive loop
        """Interactive REPL. Type '/exit' to quit."""
        print("AI Agent Platform (CLI). Напишите сообщение, '/exit' — выход.")
        loop = asyncio.get_running_loop()
        while True:
            line = (await loop.run_in_executor(None, input, "> ")).strip()
            if line in {"/exit", "/quit"}:
                break
            if not line:
                continue
            print(await self.send(line))
