"""Application entrypoint: wire the container, manage lifecycle, pick a transport.

Usage:
    python -m app.main            # CLI transport (default; no external services)
    python -m app.main telegram   # Telegram long-polling (needs token + aiogram)
    python -m app.main api        # REST API (needs fastapi + uvicorn)

The composition root builds a single :class:`Container`; ``lifespan`` guarantees
the database and other resources are set up and torn down cleanly, including on
SIGTERM/SIGINT.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.container import Container
from app.core.lifecycle import install_signal_handlers, lifespan
from app.core.logger import get_logger

_log = get_logger(__name__)


def _force_utf8_console() -> None:
    """Make stdout/stderr UTF-8 so non-ASCII (Cyrillic) prints cleanly on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # pragma: no cover - exotic stream
                pass


async def _run(transport: str) -> None:
    container = Container()
    async with lifespan(container):
        stop = asyncio.Event()
        install_signal_handlers(stop)

        if transport == "telegram":
            from app.bot.telegram import TelegramAdapter

            adapter = TelegramAdapter(
                container.gateway, token=container.settings.telegram_bot_token
            )
            await adapter.run()
        else:
            from app.bot.cli import CLIAdapter

            await CLIAdapter(container.gateway).run()


def _run_api() -> None:  # pragma: no cover - exercised via live server, not unit tests
    """Serve the REST transport with uvicorn (owns its own event loop + lifespan)."""
    import uvicorn

    from app.api.app import create_api

    container = Container()
    app = create_api(container)
    uvicorn.run(
        app,
        host=container.settings.api_host,
        port=container.settings.api_port,
        log_config=None,  # reuse our structured logging, don't override it
    )


def main() -> None:
    _force_utf8_console()
    transport = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if transport == "api":
        _run_api()
        return
    try:
        asyncio.run(_run(transport))
    except KeyboardInterrupt:  # pragma: no cover - manual interrupt
        _log.info("interrupted; exiting")


if __name__ == "__main__":
    main()
