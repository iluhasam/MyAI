"""Session memory: a bounded sliding window of the current conversation.

Held in-process for the MVP (swap for Redis in production by implementing the
same tiny surface). Keeps only the last N turns per user so prompts stay small
and within the model's context window.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque

from app.llm.base import ChatMessage


class SessionMemory:
    """Per-user ring buffer of recent chat messages."""

    def __init__(self, window: int = 30) -> None:
        self._window = window
        self._store: dict[str, Deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=window))

    def append(self, user_key: str, message: ChatMessage) -> None:
        self._store[user_key].append(message)

    def history(self, user_key: str) -> list[ChatMessage]:
        return list(self._store.get(user_key, ()))

    def clear(self, user_key: str) -> None:
        self._store.pop(user_key, None)
