"""Presentation layer: thin transport adapters (Telegram, CLI).

Adapters contain no business logic — they translate transport events into the
Gateway's ``RawInbound`` dict and render ``AgentResponse`` back to the channel.
"""

from app.bot.cli import CLIAdapter

__all__ = ["CLIAdapter"]
