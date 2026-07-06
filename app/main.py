"""Application entrypoint: wire the container, manage lifecycle, pick a transport.

Usage:
    python -m app.main            # CLI transport (default; no external services)
    python -m app.main telegram   # Telegram long-polling (needs token + aiogram)

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


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 else "cli"
    try:
        asyncio.run(_run(transport))
    except KeyboardInterrupt:  # pragma: no cover - manual interrupt
        _log.info("interrupted; exiting")


if __name__ == "__main__":
    main()
