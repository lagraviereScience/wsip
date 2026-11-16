"""Gaming activity: libraries, playtime snapshots, achievements, sync runs (spec §12, §26)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ, UpdatedAt
from app.models.catalogue import Game


class UserLibraryEntry(Base):
    """Current state of one game in a user's platform library. Playtime in minutes."""

    __tablename__ = "user_library"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "game_id"),
        CheckConstraint("playtime_forever_minutes >= 0", name="playtime_forever_nonneg"),
        CheckConstraint(
            "playtime_2weeks_minutes IS NULL OR playtime_2weeks_minutes >= 0",
            name="playtime_2weeks_nonneg",
        ),
        CheckConstraint("source IN ('steam_import', 'manual')", name="source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    # steam_import: reported by the platform. manual: the user said they own it
    # (sign-in-only mode, ADR-0014). Manual entries have unknown (NULL) playtime.
    source: Mapped[str] = mapped_column(String(16), server_default="steam_import")
    playtime_forever_minutes: Mapped[int | None] = mapped_column(Integer)
    # Steam omits playtime_2weeks for games not played recently; a successful import
    # records that as 0. NULL means unknown (e.g. the platform hides playtime).
    playtime_2weeks_minutes: Mapped[int | None] = mapped_column(Integer)
    last_played_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    first_seen_at: Mapped[CreatedAt]
    last_seen_at: Mapped[datetime] = mapped_column(TimestampTZ)
    # Set when a game disappears from the platform library (refund, licence removal).
    removed_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    updated_at: Mapped[UpdatedAt]

    game: Mapped[Game] = relationship()


class PlaytimeSnapshot(Base):
    """Append-only record of platform-reported playtime at a point in time (spec §12).

    Written on first import and whenever reported values change. Values here are
    exactly what the platform reported; estimated activity between snapshots is
    derived later and never stored in this table.
    """

    __tablename__ = "playtime_snapshots"
    __table_args__ = (
        Index("ix_playtime_snapshots_entry_captured", "library_entry_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    library_entry_id: Mapped[int] = mapped_column(ForeignKey("user_library.id", ondelete="CASCADE"))
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_sync_runs.id", ondelete="SET NULL"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(TimestampTZ)
    playtime_forever_minutes: Mapped[int] = mapped_column(Integer)
    playtime_2weeks_minutes: Mapped[int | None] = mapped_column(Integer)
    last_played_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    source: Mapped[str] = mapped_column(String(32), server_default="steam_reported")


class AchievementSummary(Base):
    __tablename__ = "achievement_summaries"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'no_stats', 'unavailable')", name="status"),
    )

    library_entry_id: Mapped[int] = mapped_column(
        ForeignKey("user_library.id", ondelete="CASCADE"), primary_key=True
    )
    achieved: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)


SYNC_ACTIVE_STATUSES = ("queued", "running")


class LibrarySyncRun(Base):
    """One library import attempt; drives onboarding progress and auditing."""

    __tablename__ = "library_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'blocked_private', 'empty', 'failed')",
            name="status",
        ),
        CheckConstraint("trigger IN ('login', 'manual', 'scheduled')", name="trigger"),
        # At most one queued/running import per user and platform.
        Index(
            "uq_library_sync_runs_one_active",
            "user_id",
            "platform",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_library_sync_runs_user_queued", "user_id", "queued_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    queued_at: Mapped[CreatedAt]
    started_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    games_seen: Mapped[int | None] = mapped_column(Integer)
    games_new: Mapped[int | None] = mapped_column(Integer)
    snapshots_written: Mapped[int | None] = mapped_column(Integer)
    # Machine-readable reason (e.g. "steam_unavailable"); never contains personal data.
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)


RATING_LABELS = {2: "loved", 1: "liked", 0: "neutral", -1: "disliked", -2: "hated"}


class UserFeedback(Base):
    """Explicit satisfaction rating of a game (spec §18): the primary training label.

    One current rating per (user, game). Loved=2, Liked=1, Neutral=0, Disliked=-1,
    Hated=-2. The game need not be owned (it may have been played elsewhere).
    """

    __tablename__ = "user_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "game_id"),
        CheckConstraint("rating BETWEEN -2 AND 2", name="rating_range"),
        CheckConstraint(
            "source IN ('library_entry', 'post_play', 'already_played')", name="source"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(String(16), server_default="library_entry")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
