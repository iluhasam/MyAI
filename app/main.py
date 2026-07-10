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
import os
import sys

from app.core.container import Container
from app.core.lifecycle import install_signal_handlers, lifespan
from app.core.logger import get_logger

_log = get_logger(__name__)


def _web_host_port(settings) -> tuple[str, int]:
    """Resolve the web bind address, honoring a host-injected PORT (Railway/Fly).

    When a ``PORT`` env var is present the platform expects us to listen on it and
    on all interfaces, so the public URL routes to us without extra config.
    """
    env_port = os.environ.get("PORT")
    if env_port and env_port.isdigit():
        return "0.0.0.0", int(env_port)
    return settings.api_host, settings.api_port


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
    host, port = _web_host_port(container.settings)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,  # reuse our structured logging, don't override it
    )


async def _run_all() -> None:  # pragma: no cover - exercised as a live process
    """Run the Telegram bot and the REST API (with the Mini App) in one process.

    One container, one lifecycle (DB/outbox), one SQLite file — so settings
    changed in the Mini App are immediately visible to the bot. This is the mode
    to deploy when the Mini App is enabled.
    """
    import uvicorn

    from app.api.app import create_api
    from app.bot.telegram import TelegramAdapter

    container = Container()
    async with lifespan(container):
        app = create_api(container, manage_lifecycle=False)  # lifecycle owned here
        host, port = _web_host_port(container.settings)
        config = uvicorn.Config(app, host=host, port=port, log_config=None)
        server = uvicorn.Server(config)
        adapter = TelegramAdapter(
            container.gateway,
            token=container.settings.telegram_bot_token,
            miniapp_url=container.settings.miniapp_url,
        )
        await asyncio.gather(server.serve(), adapter.run())


def main() -> None:
    _force_utf8_console()
    transport = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if transport == "api":
        _run_api()
        return
    if transport == "all":
        try:
            asyncio.run(_run_all())
        except KeyboardInterrupt:  # pragma: no cover - manual interrupt
            _log.info("interrupted; exiting")
        return
    try:
        asyncio.run(_run(transport))
    except KeyboardInterrupt:  # pragma: no cover - manual interrupt
        _log.info("interrupted; exiting")


if __name__ == "__main__":
    main()
