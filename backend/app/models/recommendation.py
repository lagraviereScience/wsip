"""Gamer profiles, manual preferences, recommendations and trend data (spec §11, §20, §26)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ, UpdatedAt


class UserPreference(Base):
    """A manual preference or exclusion. Takes precedence over inferred values (spec §11)."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("value IS NULL OR (value >= -1 AND value <= 1)", name="value_range"),
        CheckConstraint("value IS NOT NULL OR excluded", name="not_empty"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("game_features.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[float | None] = mapped_column(Float)
    excluded: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class UserPreferenceEvent(Base):
    """Append-only history of manual preference changes."""

    __tablename__ = "user_preference_events"
    __table_args__ = (Index("ix_user_preference_events_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    feature_id: Mapped[int] = mapped_column(ForeignKey("game_features.id", ondelete="CASCADE"))
    old_value: Mapped[float | None] = mapped_column(Float)
    new_value: Mapped[float | None] = mapped_column(Float)
    old_excluded: Mapped[bool] = mapped_column(Boolean)
    new_excluded: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[CreatedAt]


class ProfileRun(Base):
    """One computation of a user's inferred profile, with the parameters used."""

    __tablename__ = "profile_runs"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="status"),
        Index("ix_profile_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    params_version: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    games_considered: Mapped[int] = mapped_column(Integer, server_default="0")
    games_with_metadata: Mapped[int] = mapped_column(Integer, server_default="0")
    games_played: Mapped[int] = mapped_column(Integer, server_default="0")
    games_rated: Mapped[int] = mapped_column(Integer, server_default="0")
    features_inferred: Mapped[int] = mapped_column(Integer, server_default="0")
    confidence: Mapped[float] = mapped_column(Float, server_default="0")
    total_minutes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    recent_minutes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[CreatedAt]


class UserFeaturePreference(Base):
    """Current inferred preference per feature: strength and confidence kept apart (§15)."""

    __tablename__ = "user_feature_preferences"
    __table_args__ = (
        CheckConstraint("value >= -1 AND value <= 1", name="value_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("game_features.id", ondelete="CASCADE"), primary_key=True
    )
    profile_run_id: Mapped[int] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    historical: Mapped[float | None] = mapped_column(Float)
    historical_confidence: Mapped[float] = mapped_column(Float, server_default="0")
    recent: Mapped[float | None] = mapped_column(Float)
    recent_confidence: Mapped[float] = mapped_column(Float, server_default="0")
    satisfaction: Mapped[float | None] = mapped_column(Float)
    satisfaction_confidence: Mapped[float] = mapped_column(Float, server_default="0")
    # Explicit game feedback (favourite, like, not my type...): interest evidence.
    feedback: Mapped[float | None] = mapped_column(Float)
    feedback_confidence: Mapped[float] = mapped_column(Float, server_default="0")
    minutes_lifetime: Mapped[int] = mapped_column(BigInteger, server_default="0")
    minutes_recent: Mapped[int] = mapped_column(BigInteger, server_default="0")
    evidence_game_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), server_default=text("'{}'")
    )
    updated_at: Mapped[UpdatedAt]


class UserFeaturePreferenceHistory(Base):
    """Inferred values that changed in a profile run (preference update history)."""

    __tablename__ = "user_feature_preference_history"

    profile_run_id: Mapped[int] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("game_features.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[float | None] = mapped_column(Float)  # NULL = no longer inferred
    confidence: Mapped[float] = mapped_column(Float)
    historical: Mapped[float | None] = mapped_column(Float)
    recent: Mapped[float | None] = mapped_column(Float)
    satisfaction: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[float | None] = mapped_column(Float)


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        CheckConstraint("category IN ('owned', 'unowned', 'trending')", name="category"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="status"),
        CheckConstraint("data_state IN ('ok', 'incomplete', 'unavailable')", name="data_state"),
        CheckConstraint("scoring_mode IN ('ai', 'classic')", name="scoring_mode"),
        Index("ix_recommendation_runs_user_category_created", "user_id", "category", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    data_state: Mapped[str] = mapped_column(String(16), server_default="ok")
    # "content-v2", or "content-v2+<collaborative model version>".
    algorithm: Mapped[str] = mapped_column(String(64))
    # AI_GRADE mode that produced the run ('ai' | 'classic') and a fingerprint of the
    # scoring configuration (mode + parameters). Lists are only served in the mode
    # that built them, so switching modes never shows a score from the other one.
    scoring_mode: Mapped[str] = mapped_column(String(16), server_default="ai")
    config_version: Mapped[str | None] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    profile_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("profile_runs.id", ondelete="SET NULL")
    )
    # Collaborative model blended into this run, if one was deployed and usable.
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    # Satisfaction model used for ranking, if one was deployed and usable.
    satisfaction_model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    candidates_considered: Mapped[int] = mapped_column(Integer, server_default="0")
    candidates_excluded: Mapped[int] = mapped_column(Integer, server_default="0")
    items_count: Mapped[int] = mapped_column(Integer, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)  # generation time (monitoring)
    created_at: Mapped[CreatedAt]


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"
    __table_args__ = (UniqueConstraint("run_id", "game_id"),)

    run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)  # category ranking score, 0..100
    satisfaction_score: Mapped[float] = mapped_column(Float)  # content compatibility, 0..100
    backlog_score: Mapped[float | None] = mapped_column(Float)
    trend_score: Mapped[float | None] = mapped_column(Float)
    # Collaborative percentile 0..100 for this user, when a model was used.
    collaborative_score: Mapped[float | None] = mapped_column(Float)
    # Calibrated P(satisfied) from the satisfaction model, 0..1, when one was used.
    predicted_satisfaction: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    metadata_confidence: Mapped[float] = mapped_column(Float)
    group_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    candidate_sources: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))


class GameDiscoverySource(Base):
    """Why a game entered the catalogue as an unowned candidate (provenance)."""

    __tablename__ = "game_discovery_sources"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen_at: Mapped[CreatedAt]
    last_seen_at: Mapped[datetime] = mapped_column(TimestampTZ)


class GamePrice(Base):
    """Steam store price for one storefront country (presented separately from scores)."""

    __tablename__ = "game_prices"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    country_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    is_free: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    final_price_cents: Mapped[int | None] = mapped_column(Integer)
    original_price_cents: Mapped[int | None] = mapped_column(Integer)
    discount_pct: Mapped[int | None] = mapped_column(SmallInteger)
    formatted_final_price: Mapped[str | None] = mapped_column(String(32))
    formatted_original_price: Mapped[str | None] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)


class PlayerCountSample(Base):
    """Concurrent players reported by ISteamUserStats/GetNumberOfCurrentPlayers."""

    __tablename__ = "player_count_samples"
    __table_args__ = (Index("ix_player_count_samples_sampled_at", "sampled_at"),)

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    sampled_at: Mapped[datetime] = mapped_column(TimestampTZ, primary_key=True)
    player_count: Mapped[int] = mapped_column(Integer)


class PlayerCountDaily(Base):
    """Daily aggregate of the samples; the input of trend scoring (spec §20.3)."""

    __tablename__ = "player_count_daily"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    avg_players: Mapped[float] = mapped_column(Float)
    max_players: Mapped[int] = mapped_column(Integer)
    samples: Mapped[int] = mapped_column(SmallInteger)


class PlayerCountPass(Base):
    """One sampling pass of the player-count source: for freshness and reliability.

    Trend scores are paused when the source is stale (no successful pass recently)
    instead of being computed from old data (prompt 6 A, spec §38)."""

    __tablename__ = "player_count_passes"
    __table_args__ = (Index("ix_player_count_passes_started", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), server_default="steam_current_players")
    started_at: Mapped[datetime] = mapped_column(TimestampTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    tracked: Mapped[int] = mapped_column(Integer, server_default="0")
    sampled: Mapped[int] = mapped_column(Integer, server_default="0")
    no_data: Mapped[int] = mapped_column(Integer, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
