"""Shared pytest fixtures.

Builds a fully-wired :class:`Container` against a throwaway SQLite file and the
deterministic mock LLM, so the whole pipeline is exercised with no external
services. Demonstrates the DI container's override/lifecycle in a test setting.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from app.core.config import Settings
from app.core.container import Container
from app.core.lifecycle import shutdown, startup


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    db_file = tmp_path / "test.db"
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db_file}",
        llm_provider="mock",
        app_log_level="WARNING",
        # Keep the background relay off so tests drive the publisher deterministically.
        outbox_publisher_enabled=False,
    )


@pytest_asyncio.fixture()
async def container(settings: Settings) -> AsyncIterator[Container]:
    c = Container(settings=settings)
    await startup(c)
    try:
        yield c
    finally:
        await shutdown(c)
