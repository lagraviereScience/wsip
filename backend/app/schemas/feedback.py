"""API shapes for behavioural events, game feedback, satisfaction and privacy (Stage 4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ClientEventType = Literal["impression", "click", "detail_view", "store_visit"]
Surface = Literal["dashboard", "play", "buy", "trending", "game_page", "profile", "library"]
FeedbackKind = Literal[
    "like",
    "dislike",
    "favourite",
    "save_for_later",
    "not_interested",
    "not_my_type",
    "already_played",
]
DismissalReason = Literal["price", "timing", "owned_elsewhere", "other"]
MAX_CONTEXT_BYTES = 1024


class ExposureIn(BaseModel):
    """Where an action happened. Category and model come from the stored run."""

    recommendation_run_id: int | None = Field(default=None, ge=1)
    position: int | None = Field(default=None, ge=1, le=1000)
    surface: Surface | None = None


class EventIn(ExposureIn):
    type: ClientEventType
    game_id: int = Field(ge=1)
    # Client-generated; the same key twice is stored once.
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9:_.\-]+$")
    occurred_at: datetime | None = None
    context: dict[str, int | float | bool | str] | None = None

    @field_validator("context")
    @classmethod
    def _small_context(
        cls, v: dict[str, int | float | bool | str] | None
    ) -> dict[str, int | float | bool | str] | None:
        if v is not None and len(str(v)) > MAX_CONTEXT_BYTES:
            raise ValueError("context too large")
        return v


class EventsIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=100)


class EventsOut(BaseModel):
    accepted: int
    duplicates: int
    rejected: int


class ReactionIn(ExposureIn):
    on: bool = True
    reason: DismissalReason | None = None  # only for not_interested


class SatisfactionIn(ExposureIn):
    rating: int | None = Field(ge=-2, le=2)  # Loved 2 ... Hated -2; null clears
    source: Literal["post_play", "already_played"] = "post_play"


class GameFeedbackOut(BaseModel):
    game_id: int
    reaction: Literal["like", "dislike"] | None = None
    favourite: bool = False
    saved: bool = False
    dismissal: Literal["not_interested", "not_my_type"] | None = None
    dismissal_reason: DismissalReason | None = None
    already_played: bool = False
    rating: int | None = None
    rating_source: str | None = None

    @classmethod
    def from_state(cls, game_id: int, state: Any | None, rating: Any | None) -> GameFeedbackOut:
        """From a ``UserGameReaction`` and a ``UserFeedback`` row (either may be None)."""
        return cls(
            game_id=game_id,
            reaction=state.reaction if state else None,
            favourite=bool(state and state.favourite),
            saved=bool(state and state.saved),
            dismissal=state.dismissal if state else None,
            dismissal_reason=state.dismissal_reason if state else None,
            already_played=bool(state and state.already_played),
            rating=rating.rating if rating else None,
            rating_source=rating.source if rating else None,
        )


class FeedbackGameOut(GameFeedbackOut):
    name: str
    steam_appid: str | None
    capsule_image_url: str | None
    owned: bool
    updated_at: datetime | None


class FeedbackListOut(BaseModel):
    games: list[FeedbackGameOut]


class EventOut(BaseModel):
    id: int
    event_type: str
    occurred_at: datetime
    game_id: int | None
    game_name: str | None
    feature: str | None
    category: str | None
    position: int | None
    model_version: str | None
    surface: str | None
    metadata: dict[str, Any]


class EventHistoryOut(BaseModel):
    events: list[EventOut]
    next_before: int | None


class PromptOut(BaseModel):
    game_id: int
    name: str
    capsule_image_url: str | None
    minutes_since_recommended: int
    question: str


class PromptStatusOut(BaseModel):
    prompt: PromptOut | None


class PromptActionIn(BaseModel):
    action: Literal["shown", "snooze", "decline"]


class GamePageOut(BaseModel):
    game_id: int
    name: str
    steam_appid: str | None
    header_image_url: str | None
    short_description: str | None
    release_date: date | None
    tags: list[str]
    owned: bool
    playtime_minutes: int | None
    feedback: GameFeedbackOut
    # Live content Match for this user (not stored), with its breakdown.
    match: float | None
    confidence_label: Literal["low", "medium", "high"] | None
    reasons: list[dict[str, Any]]
    contributions: list[dict[str, Any]]
    # The latest recommendation list containing this game, for exposure context.
    recommendation_run_id: int | None
    category: str | None
    rank: int | None
    review: dict[str, Any] | None
    price: dict[str, Any] | None
    # Time to beat in hours, from IGDB when enabled; None = unavailable.
    completion: dict[str, Any] | None = None
    # Where each kind of data came from and when it was fetched (prompt 6 B).
    sources: list[dict[str, Any]] = []


class PrivacyOut(BaseModel):
    contribute_to_global_training: bool
    allow_scheduled_sync: bool
    updated_at: datetime


class PrivacyIn(BaseModel):
    contribute_to_global_training: bool | None = None
    allow_scheduled_sync: bool | None = None


class DeleteAccountIn(BaseModel):
    confirm: Literal["DELETE"]


class ExportMeta(BaseModel):
    user_id: uuid.UUID
    exported_at: datetime
    format_version: int = 1
