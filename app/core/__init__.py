"""Infrastructure core: configuration, logging, exceptions, event bus, DI, lifecycle.

This package must contain **no business logic** — only infrastructure wiring.
"""

from app.core.config import Settings, get_settings
from app.core.container import Container
from app.core.events import Event, EventBus
from app.core.exceptions import (
    AgentError,
    ConfigurationError,
    LLMError,
    PlatformError,
    ValidationError,
)
from app.core.logger import get_logger, setup_logging

__all__ = [
    "Settings",
    "get_settings",
    "Container",
    "Event",
    "EventBus",
    "PlatformError",
    "ConfigurationError",
    "ValidationError",
    "AgentError",
    "LLMError",
    "get_logger",
    "setup_logging",
]
