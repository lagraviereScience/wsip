"""Shared game catalogue and canonical taxonomy (spec §8-§10, §26 "Game catalogue").

Provenance model:
    provider_tags            raw vocabulary of each provider (e.g. Steam tag 1702 "Crafting")
    game_provider_tags       raw tags as imported for each game, with provider weight/rank
    provider_tag_mappings    versioned mapping raw tag -> canonical feature (+ confidence)
    game_feature_values      derived canonical values, one row per (game, feature, source)

Unknown is represented by the absence of a game_feature_values row, never by 0.
Values are stored only on the feature a tag maps to; parents are NOT filled in,
so a roll-up must take the max over a subtree rather than summing it (spec §10).
"""

from __future__ import annotations

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ, UpdatedAt


class Game(Base):
    """Canonical game record, shared by every user and every platform."""

    __tablename__ = "games"
    __table_args__ = (
        Index("ix_games_normalized_name", "normalized_name"),
        CheckConstraint(
            "merged_into_game_id IS NULL OR merged_into_game_id <> id", name="no_self_merge"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    normalized_name: Mapped[str] = mapped_column(String(500))
    # game | dlc | software | video | hardware | unknown - from the best available source.
    game_type: Mapped[str] = mapped_column(String(16), server_default="unknown")
    short_description: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    is_free: Mapped[bool | None] = mapped_column(Boolean)
    header_image_url: Mapped[str | None] = mapped_column(Text)
    capsule_image_url: Mapped[str | None] = mapped_column(Text)
    developers: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    publishers: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Duplicate resolution: a merged record points at the surviving canonical game.
    merged_into_game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    external_ids: Mapped[list[ExternalGameId]] = relationship(back_populates="game")


class ExternalGameId(Base):
    __tablename__ = "external_game_ids"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    # steam | igdb | rawg | ... (Steam AppID is the first identifier, spec §8).
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[CreatedAt]

    game: Mapped[Game] = relationship(back_populates="external_ids")


class GameSource(Base):
    """Latest ingestion state of a game per metadata provider (provenance + refresh)."""

    __tablename__ = "game_sources"
    __table_args__ = (
        UniqueConstraint("game_id", "provider"),
        CheckConstraint("status IN ('ok', 'not_found', 'error')", name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)
    mapping_version: Mapped[int | None] = mapped_column(Integer)


class GameReviewSummary(Base):
    __tablename__ = "game_review_summaries"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    review_count: Mapped[int | None] = mapped_column(Integer)
    percent_positive: Mapped[int | None] = mapped_column(SmallInteger)
    label: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)


class FeatureCategory(Base):
    """Taxonomy category. New categories are rows, not schema changes (spec §10)."""

    __tablename__ = "feature_categories"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    # Category weight group used by the content score (spec §16): genres and themes share one.
    scoring_group: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class GameFeature(Base):
    """A canonical, hierarchical taxonomy feature (spec §10)."""

    __tablename__ = "game_features"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'deprecated')", name="status"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="no_self_parent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("feature_categories.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_features.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    category: Mapped[FeatureCategory] = relationship()


class ProviderTag(Base):
    """A provider's raw vocabulary entry (Steam tag, Steam category, IGDB genre, ...)."""

    __tablename__ = "provider_tags"
    __table_args__ = (
        UniqueConstraint("provider", "kind", "external_id"),
        Index("ix_provider_tags_lower_name", "provider", "kind", func.lower(text("name"))),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))  # tag | category | genre | ...
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class GameProviderTag(Base):
    """Raw provider tags as imported for a game (kept so mappings can be re-applied)."""

    __tablename__ = "game_provider_tags"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    provider_tag_id: Mapped[int] = mapped_column(
        ForeignKey("provider_tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    weight: Mapped[int | None] = mapped_column(Integer)  # e.g. Steam community vote weight
    rank: Mapped[int | None] = mapped_column(SmallInteger)  # 0 = most prominent
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)


class ProviderTagMapping(Base):
    """Versioned mapping from a provider's raw tag to a canonical feature (spec §10)."""

    __tablename__ = "provider_tag_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "tag_kind",
            "original_tag",
            "feature_id",
            "mapping_version",
            name="uq_provider_tag_mappings_identity",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("status IN ('active', 'superseded')", name="status"),
        Index("ix_provider_tag_mappings_active", "provider", "tag_kind", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    tag_kind: Mapped[str] = mapped_column(String(32))
    original_tag: Mapped[str] = mapped_column(String(200))
    feature_id: Mapped[int] = mapped_column(ForeignKey("game_features.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    mapping_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[CreatedAt]


class GameFeatureValue(Base):
    """Derived canonical feature value for a game from one source (spec §14)."""

    __tablename__ = "game_feature_values"
    __table_args__ = (
        CheckConstraint("value >= 0 AND value <= 1", name="value_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_game_feature_values_feature_id", "feature_id", "value"),
    )

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("game_features.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    mapping_version: Mapped[int] = mapped_column(Integer)
    # Which raw tags produced the value, e.g. [{"tag": "Crafting", "weight": 412, "rank": 3}].
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    updated_at: Mapped[UpdatedAt]


class GameCompletionTime(Base):
    """How long a game takes to beat, from an authorised source (IGDB).

    Seconds, as published by the source. A row with all values NULL records that the
    source was asked and has no data, so it is not asked again until it is stale."""

    __tablename__ = "game_completion_times"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64))
    hastily_seconds: Mapped[int | None] = mapped_column(Integer)
    normally_seconds: Mapped[int | None] = mapped_column(Integer)
    completely_seconds: Mapped[int | None] = mapped_column(Integer)
    submissions: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(TimestampTZ)
