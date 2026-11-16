"""API shapes for the gamer profile, preferences and recommendations (Stage 3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.feedback import GameFeedbackOut

Origin = Literal["inferred", "manual"]
ConfidenceLabel = Literal["low", "medium", "high"]


def confidence_label(value: float) -> ConfidenceLabel:
    if value >= 0.6:
        return "high"
    if value >= 0.35:
        return "medium"
    return "low"


# --- Profile -------------------------------------------------------------------


class EvidenceGameOut(BaseModel):
    game_id: int
    name: str
    capsule_image_url: str | None
    playtime_minutes: int | None
    rating: int | None


class InferredOut(BaseModel):
    value: float
    confidence: float
    historical: float | None
    historical_confidence: float
    recent: float | None
    recent_confidence: float
    satisfaction: float | None
    satisfaction_confidence: float
    feedback: float | None = None
    feedback_confidence: float = 0.0


class ManualOut(BaseModel):
    value: float | None
    excluded: bool
    updated_at: datetime


class FeaturePreferenceOut(BaseModel):
    slug: str
    name: str
    category: str
    category_name: str
    group: str
    parent: str | None
    value: float | None  # effective: manual if set, else inferred
    confidence: float  # effective
    origin: Origin | None
    excluded: bool
    inferred: InferredOut | None
    manual: ManualOut | None
    minutes_lifetime: int
    minutes_recent: int
    evidence: list[EvidenceGameOut]


class ProfileRunOut(BaseModel):
    id: int
    created_at: datetime
    params_version: str
    games_considered: int
    games_with_metadata: int
    games_played: int
    games_rated: int
    features_inferred: int
    confidence: float
    total_minutes: int
    recent_minutes: int


class ModeBalanceOut(BaseModel):
    singleplayer_minutes: int
    multiplayer_minutes: int
    singleplayer_share: float | None  # of the two, None when neither is known


class ProfileOut(BaseModel):
    status: Literal["ready", "pending"]
    run: ProfileRunOut | None
    features: list[FeaturePreferenceOut]
    mode_balance: ModeBalanceOut
    influential_games: list[EvidenceGameOut]


class PreferenceIn(BaseModel):
    """value: -1..1 or null (no manual value); excluded: hard exclusion."""

    value: float | None = Field(default=None, ge=-1, le=1)
    excluded: bool = False

    @model_validator(mode="after")
    def _round(self) -> PreferenceIn:
        if self.value is not None:
            self.value = round(self.value, 2)
        return self


class PreferenceEventOut(BaseModel):
    feature: str
    name: str
    old_value: float | None
    new_value: float | None
    old_excluded: bool
    new_excluded: bool
    created_at: datetime


class FeatureHistoryPointOut(BaseModel):
    computed_at: datetime
    value: float | None
    confidence: float
    historical: float | None
    recent: float | None
    satisfaction: float | None


class PreferenceHistoryOut(BaseModel):
    manual_changes: list[PreferenceEventOut]
    feature: str | None = None
    inferred_history: list[FeatureHistoryPointOut] = []


# --- Recommendations --------------------------------------------------------------


class ReasonOut(BaseModel):
    code: str
    text: str
    polarity: Literal["positive", "negative", "info"]
    feature: str | None = None
    points: float | None = None


class ContributionOut(BaseModel):
    feature: str
    name: str
    group: str
    game_features: list[str]
    preference: float
    preference_confidence: float
    origin: Origin
    game_value: float
    metadata_confidence: float
    points: float


class GroupScoreOut(BaseModel):
    group: str
    weight: float
    score: float | None
    reliability: float
    evidence: float


class PriceOut(BaseModel):
    is_free: bool
    final_cents: int | None
    original_cents: int | None
    discount_pct: int | None
    formatted_final: str | None
    formatted_original: str | None
    country: str
    fetched_at: datetime


class ReviewOut(BaseModel):
    count: int | None
    percent_positive: int | None
    label: str | None


class RecommendationOut(BaseModel):
    rank: int
    game_id: int
    name: str
    steam_appid: str | None
    header_image_url: str | None
    capsule_image_url: str | None
    short_description: str | None
    release_date: date | None
    owned: bool
    playtime_minutes: int | None
    last_played_at: datetime | None
    score: float
    satisfaction_score: float
    backlog_score: float | None
    trend_score: float | None
    confidence: float
    confidence_label: ConfidenceLabel
    metadata_confidence: float
    group_scores: list[GroupScoreOut]
    contributions: list[ContributionOut]
    reasons: list[ReasonOut]
    candidate_sources: list[str]
    tags: list[str]
    review: ReviewOut | None
    price: PriceOut | None
    collaborative_score: float | None = None
    # Calibrated P(satisfied), 0..1, when a satisfaction model ranked this list.
    predicted_satisfaction: float | None = None
    feedback: GameFeedbackOut | None = None


class RecommendationRunOut(BaseModel):
    id: int
    category: str
    created_at: datetime
    algorithm: str  # "content-v2", or "content-v2+<collaborative version>"
    # AI_GRADE mode that built the list ("ai" | "classic") and the scoring
    # configuration fingerprint (mode + parameters).
    scoring_mode: Literal["ai", "classic"] = "ai"
    config_version: str | None = None
    model_version_id: int | None = None
    satisfaction_model_version_id: int | None = None
    data_state: Literal["ok", "incomplete", "unavailable"]
    note: str | None
    candidates_considered: int
    candidates_excluded: int
    items_count: int


class TrendStatusOut(BaseModel):
    days_collected: int
    days_needed: int
    first_day: date | None
    games_tracked: int
    # Source health (prompt 6 A): where counts come from, how fresh and reliable.
    source: str | None = None
    last_success_at: datetime | None = None
    freshness_hours: float | None = None
    reliability_7d: float | None = None
    max_staleness_hours: float | None = None


class PopularNowOut(BaseModel):
    game_id: int
    name: str
    steam_appid: str | None
    capsule_image_url: str | None
    players: int
    sampled_at: datetime
    satisfaction_score: float
    confidence_label: ConfidenceLabel
    reasons: list[ReasonOut]


class RecommendationsOut(BaseModel):
    category: Literal["owned", "unowned", "trending"]
    status: Literal["ready", "pending"]
    # The deployment's active scoring mode (AI_GRADE). A list is only served in the
    # mode that built it; after a switch the list is "pending" until rebuilt.
    scoring_mode: Literal["ai", "classic"] = "ai"
    # "match": an uncalibrated compatibility score, never a probability (§18, §33).
    # "calibrated_satisfaction": the list was ranked by a deployed, calibrated
    # satisfaction model; items carry predicted_satisfaction.
    score_kind: Literal["match", "calibrated_satisfaction"] = "match"
    run: RecommendationRunOut | None
    items: list[RecommendationOut]
    filtered_out: int = 0
    hidden_by_feedback: int = 0
    total: int = 0  # items after filters, before ``limit``
    trend_status: TrendStatusOut | None = None
    popular_now: list[PopularNowOut] = []
    attribution: str = "Game data provided by Steam."
