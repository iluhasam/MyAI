"""Data-access layer: async SQLAlchemy 2.0 engine, ORM models, repositories.

MVP uses SQLite (aiosqlite); switching ``DATABASE_URL`` to a PostgreSQL DSN
(``postgresql+asyncpg://...``) is the only change needed for production.
"""

from app.database.database import Database
from app.database.models import Base, DialogMessage, OutboxEvent, User
from app.database.repositories import (
    DialogRepository,
    OutboxRepository,
    UserRepository,
)

__all__ = [
    "Database",
    "Base",
    "User",
    "DialogMessage",
    "OutboxEvent",
    "UserRepository",
    "DialogRepository",
    "OutboxRepository",
]
