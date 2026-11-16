"""Users, connected gaming platforms, sessions and privacy settings (spec §26 "Users")."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ, UpdatedAt


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="status"),)

    # Time-ordered UUIDv7 (PostgreSQL 18): non-enumerable, index-friendly.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    display_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    platforms: Mapped[list[ConnectedPlatform]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    privacy: Mapped[UserPrivacySettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


GAME_DETAILS_STATUSES = ("unknown", "accessible", "empty", "private", "error")


class ConnectedPlatform(Base):
    """A verified link between a user and an external platform identity."""

    __tablename__ = "connected_platforms"
    __table_args__ = (
        # One platform identity belongs to exactly one user (account-linking safeguard)...
        UniqueConstraint("platform", "external_user_id"),
        # ...and a user links at most one identity per platform.
        UniqueConstraint("user_id", "platform"),
        CheckConstraint(
            "game_details_status IN ('unknown', 'accessible', 'empty', 'private', 'error')",
            name="game_details_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32))
    # SteamID64 for Steam. Text, because other platforms use non-numeric IDs.
    external_user_id: Mapped[str] = mapped_column(String(64))
    profile_name: Mapped[str | None] = mapped_column(String(200))
    profile_url: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # Steam communityvisibilitystate: 1 = private/friends-only, 3 = public.
    profile_visibility: Mapped[int | None] = mapped_column(SmallInteger)
    game_details_status: Mapped[str] = mapped_column(String(16), server_default="unknown")
    game_details_checked_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    # True when games are visible but every playtime is zero ("keep total playtime private").
    playtime_appears_hidden: Mapped[bool] = mapped_column(Boolean, server_default="false")
    last_synced_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    connected_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    user: Mapped[User] = relationship(back_populates="platforms")


class UserSession(Base):
    """Server-side session. Only a SHA-256 hash of the cookie token is stored."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_expires_at", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[CreatedAt]
    expires_at: Mapped[datetime] = mapped_column(TimestampTZ)
    last_seen_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TimestampTZ)


class UserPrivacySettings(Base):
    __tablename__ = "user_privacy_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Opt-out of contributing behaviour data to global model training (spec §23, §34).
    contribute_to_global_training: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Steam Web API terms: retrieve user data only at the user's request. Daily
    # re-syncs run only while this is enabled (shown and switchable in Settings).
    allow_scheduled_sync: Mapped[bool] = mapped_column(Boolean, server_default="true")
    updated_at: Mapped[UpdatedAt]

    user: Mapped[User] = relationship(back_populates="privacy")
