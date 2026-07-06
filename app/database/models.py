"""ORM models (SQLAlchemy 2.0 typed / declarative mapping).

Includes the ``OutboxEvent`` table that powers the transactional Outbox pattern:
domain writes and the event that describes them are committed in one DB
transaction, then relayed to the event bus by a background publisher — giving
at-least-once delivery even if the process crashes mid-publish.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class OutboxStatus(str, Enum):
    PENDING = "pending"      # never attempted yet
    PUBLISHED = "published"  # relayed successfully (terminal)
    FAILED = "failed"        # attempt failed, still retryable
    DEAD = "dead"            # exceeded max attempts — dead-letter (terminal)


class User(Base):
    """A platform user (long-term memory of identity & preferences)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # External identifier from the transport (e.g. Telegram user id).
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    messages: Mapped[list["DialogMessage"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("uq_user_channel_external", "channel", "external_id", unique=True),
    )


class UserPreference(Base):
    """Per-user settings (currently: the selected model alias).

    A separate table (rather than columns on ``users``) so new preferences can be
    added without migrating the users table — and ``create_all`` provisions it
    cleanly alongside an already-populated database.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    model_alias: Mapped[str] = mapped_column(String(64))
    # Communication style: a catalog alias, or "свой" with free text in persona_custom.
    persona_alias: Mapped[str | None] = mapped_column(String(64), default=None)
    persona_custom: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class DialogMessage(Base):
    """A single turn of conversation (session / long dialog history)."""

    __tablename__ = "dialog_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="messages")


class SemanticRecord(Base):
    """A persisted semantic-memory fragment: text + its embedding vector.

    Makes associative memory survive restarts (it used to live only in RAM). The
    vector is stored as JSON; cosine search loads a user's rows and ranks them.
    A production build would move this to a vector DB (Qdrant/pgvector).
    """

    __tablename__ = "semantic_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(160), index=True)
    text: Mapped[str] = mapped_column(Text)
    vector_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OutboxEvent(Base):
    """Durable event record written in the same transaction as the domain change."""

    __tablename__ = "outbox_events"

    # BigInteger in prod (PostgreSQL); auto-degrades to INTEGER on SQLite.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    event_name: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=OutboxStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_outbox_status_created", "status", "created_at"),
    )
