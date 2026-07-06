"""Application lifecycle: startup / shutdown and OS-signal handling.

Owns the ordered bring-up and graceful teardown of shared resources so that
connection pools are always released, even on SIGTERM/SIGINT. Used by the app
entrypoint (``app.main``) and by tests that need a fully-wired container.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.container import Container
from app.core.logger import get_logger, setup_logging

_log = get_logger(__name__)


async def startup(container: Container) -> None:
    """Initialise resources in dependency order (logging -> db schema)."""
    setup_logging(container.settings.app_log_level)
    _log.info("starting up", extra={"env": container.settings.app_env.value})
    await container.database.connect()
    await container.database.create_all()
    _log.info("startup complete")


async def shutdown(container: Container) -> None:
    """Release resources in reverse order. Safe to call more than once."""
    _log.info("shutting down")
    await container.database.disconnect()
    _log.info("shutdown complete")


@asynccontextmanager
async def lifespan(container: Container) -> AsyncIterator[Container]:
    """Async context manager wrapping startup/shutdown for the app entrypoint."""
    await startup(container)
    try:
        yield container
    finally:
        await shutdown(container)


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Wire SIGTERM/SIGINT to set ``stop_event`` for a clean async shutdown.

    Falls back silently on platforms/loops where signal handlers are unavailable
    (e.g. Windows ProactorEventLoop), where KeyboardInterrupt handling suffices.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform dependent
            _log.debug("signal handler not installed", extra={"signal": sig.name})
