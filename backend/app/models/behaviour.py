"""Behavioural events and explicit game feedback (spec §21, §22, prompt 4 A-C).

- ``behaviour_events`` is the append-only log. Rows are never updated; feedback
  changes and undos are new events. Client-reported events are de-duplicated by
  ``(user_id, idempotency_key)``.
- ``user_game_reactions`` is the *current* feedback state per (user, game), derived
  from the user's latest actions. Profiles, exclusions and training read this
  table, so undoing a reaction fully reverts its effect while the log keeps the
  history.
- ``satisfaction_prompts`` remembers which post-play questions were shown, snoozed
  or declined, so users are not asked repeatedly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ, UpdatedAt

# Events a browser may submit (exposure and navigation). Everything else is written
# by the server as a side effect of a validated action, so the log can never
# disagree with the feedback state.
CLIENT_EVENT_TYPES = ("impression", "click", "detail_view", "store_visit")
# Explicit feedback toggles; metadata.state is "on" or "off" (undo).
FEEDBACK_EVENT_TYPES = (
    "like",
    "dislike",
    "favourite",
    "save_for_later",
    "not_interested",
    "not_my_type",
    "already_played",
)
SERVER_EVENT_TYPES = (
    "satisfaction",  # metadata: rating (-2..2) or null when cleared, source
    "satisfaction_prompt",  # metadata: action shown | snoozed | declined
    "playtime_change",  # metadata: delta_minutes, total_minutes, sync_run_id
    "feature_preference",  # manual preference / exclusion change (feature_id set)
)
EVENT_TYPES = CLIENT_EVENT_TYPES + FEEDBACK_EVENT_TYPES + SERVER_EVENT_TYPES

SURFACES = ("dashboard", "play", "buy", "trending", "game_page", "profile", "library")
DISMISSAL_REASONS = ("price", "timing", "owned_elsewhere", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class BehaviourEvent(Base):
    __tablename__ = "behaviour_events"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="event_type"),
        CheckConstraint(f"surface IS NULL OR {_in('surface', SURFACES)}", name="surface"),
        CheckConstraint("position IS NULL OR position >= 1", name="position"),
        Index("ix_behaviour_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_behaviour_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_behaviour_events_game", "game_id"),
        Index("ix_behaviour_events_run", "recommendation_run_id"),
        Index(
            "uq_behaviour_events_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    feature_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_features.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(32))
    # When it happened (client clock, clamped server-side) and when we stored it.
    occurred_at: Mapped[datetime] = mapped_column(TimestampTZ)
    received_at: Mapped[CreatedAt]
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    # Exposure context: which recommendation, list, rank and model produced it.
    recommendation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="SET NULL")
    )
    category: Mapped[str | None] = mapped_column(String(16))
    position: Mapped[int | None] = mapped_column(SmallInteger)
    model_version: Mapped[str | None] = mapped_column(String(64))
    surface: Mapped[str | None] = mapped_column(String(16))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )


class UserGameReaction(Base):
    """Current explicit feedback on one game. A row with nothing set is deleted."""

    __tablename__ = "user_game_reactions"
    __table_args__ = (
        CheckConstraint("reaction IS NULL OR reaction IN ('like', 'dislike')", name="reaction"),
        CheckConstraint(
            "dismissal IS NULL OR dismissal IN ('not_interested', 'not_my_type')",
            name="dismissal",
        ),
        CheckConstraint(
            f"dismissal_reason IS NULL OR {_in('dismissal_reason', DISMISSAL_REASONS)}",
            name="dismissal_reason",
        ),
        CheckConstraint(
            "dismissal_reason IS NULL OR dismissal = 'not_interested'",
            name="reason_needs_not_interested",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    reaction: Mapped[str | None] = mapped_column(String(8))
    favourite: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    saved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    dismissal: Mapped[str | None] = mapped_column(String(16))
    dismissal_reason: Mapped[str | None] = mapped_column(String(16))
    already_played: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    @property
    def is_empty(self) -> bool:
        return not (
            self.reaction or self.favourite or self.saved or self.dismissal or self.already_played
        )


class SatisfactionPrompt(Base):
    """Post-play question state for one game (spec §18; prompt 4 B)."""

    __tablename__ = "satisfaction_prompts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    times_shown: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_shown_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    snoozed_until: Mapped[datetime | None] = mapped_column(TimestampTZ)
    declined: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    answered_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    created_at: Mapped[CreatedAt]
