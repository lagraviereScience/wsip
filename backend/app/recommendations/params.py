"""Tunable parameters of the content-based baseline (spec §12, §13, §16, §20).

Every number here is a documented starting value, not a fitted one. The whole set
is versioned: each profile and recommendation run stores ``PARAMS_VERSION`` and the
parameters it used, so results stay reproducible after tuning. Overrides come from
the ``RECOMMENDER_OVERRIDES`` setting (a JSON object of field -> value); see
docs/RECOMMENDATIONS.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any

PARAMS_VERSION = "content-v2"


def _default_feedback_values() -> dict[str, float]:
    # Spec §22 signal interpretation, as feature-level evidence (-1..1). "Not
    # interested" and "Already played" carry no feature evidence: a game can be
    # rejected for its price or timing, which says nothing about its gameplay.
    return {
        "favourite": 1.0,
        "like": 0.6,
        "save_for_later": 0.3,
        "dislike": -0.6,
        "not_my_type": -1.0,
    }


def _default_feedback_weights() -> dict[str, float]:
    # How much evidence one reaction is, relative to one explicit rating (1.0).
    return {
        "favourite": 1.0,
        "like": 0.7,
        "save_for_later": 0.3,
        "dislike": 0.7,
        "not_my_type": 1.0,
    }


def _default_group_weights() -> dict[str, float]:
    # Spec §16 category weights.
    return {
        "genres_and_themes": 0.25,
        "gameplay_mechanics": 0.30,
        "game_modes": 0.20,
        "game_structure": 0.15,
        "pace_and_complexity": 0.10,
    }


@dataclass(frozen=True, slots=True)
class EngineParams:
    # --- Playtime transforms (spec §12) ---------------------------------------
    lifetime_cap_hours: float = 1000.0  # H_total = ln(1+min(h,cap))/ln(1+cap)
    recent_scale_hours: float = 8.0  # H_recent = 1 - exp(-h_recent/scale)
    recency_half_life_days: float = 90.0  # R = 2^(-days/half_life)

    # --- Behavioural preference (spec §13) ------------------------------------
    # Lift = share of the player's (log-scaled) playtime in a category that goes to
    # a feature, divided by that feature's share of the catalogue. log2(lift)/span
    # gives a value in [-1, 1]; span 2 means 4x over-representation = +1.
    behaviour_lift_span: float = 2.0
    # Not playing something is weak evidence of dislike: cap negative values.
    behaviour_min_value: float = -0.5
    # Behaviour is a weaker signal than stated satisfaction: cap its confidence.
    behaviour_max_confidence: float = 0.6
    # Confidence grows with evidence n (games carrying the feature): 1-exp(-n/k).
    behaviour_evidence_k: float = 3.0
    # Historical vs recent blend for the behavioural component.
    recent_blend: float = 0.3
    # A lift needs catalogue context: features rarer than this are not scored.
    min_catalogue_prevalence: float = 0.002

    # --- Satisfaction preference (explicit ratings, spec §18) -----------------
    satisfaction_prior_weight: float = 1.0  # shrinks means towards 0 with few ratings
    satisfaction_evidence_k: float = 1.5
    satisfaction_weight: float = 1.0  # vs behaviour_weight when combining
    behaviour_weight: float = 0.5

    # --- Explicit game feedback (spec §22; prompt 4 C) -------------------------
    # Reactions on recommendation cards are interest evidence: stronger than
    # playtime, weaker than a post-play satisfaction rating.
    feedback_values: dict[str, float] = field(default_factory=_default_feedback_values)
    feedback_weights: dict[str, float] = field(default_factory=_default_feedback_weights)
    feedback_prior_weight: float = 1.0
    feedback_evidence_k: float = 1.5
    feedback_weight: float = 0.8  # combination weight vs satisfaction 1.0, behaviour 0.5

    # --- Compatibility (spec §16) ---------------------------------------------
    group_weights: dict[str, float] = field(default_factory=_default_group_weights)
    # Preferences below this confidence are treated as unknown (backed off to parent).
    min_preference_confidence: float = 0.1
    # Score = 50 + 50 * S * E/(E + shrink_k): thin evidence stays near neutral.
    evidence_shrink_k: float = 0.5
    # Hard exclusion: a game is excluded when it carries the excluded feature (or a
    # descendant) with at least this value. 0.3 is the derivation's presence floor,
    # so any Steam-tag evidence at all excludes.
    exclusion_min_value: float = 0.3

    # --- Owned ranking (spec §20.1) -------------------------------------------
    owned_satisfaction_weight: float = 0.85
    owned_backlog_weight: float = 0.15
    backlog_unplayed_scale_hours: float = 20.0  # U = exp(-hours/20)
    backlog_dormancy_scale_days: float = 90.0  # D = 1 - exp(-days/90)
    backlog_u_weight: float = 0.65
    backlog_d_weight: float = 0.35
    # Games already well known to the player are not "games to play next".
    owned_exclude_min_hours: float = 100.0
    owned_exclude_recent_days: int = 14  # played in the last N days: already playing

    # --- Category ranking (spec §20; prompt 5 C) ------------------------------
    # Satisfaction is predicted P(satisfied) x 100 when a satisfaction model is
    # deployed, else Match. It must stay the main signal in every category.
    unowned_satisfaction_weight: float = 1.0

    # --- Unowned candidates ----------------------------------------------------
    unowned_min_reviews: int = 200  # quality floor for discovery candidates
    similar_min_cosine: float = 0.6  # "Similar to <favourite>" threshold

    # --- Trending (spec §20.3) -------------------------------------------------
    trend_epsilon: float = 10.0
    trend_short_days: int = 7
    trend_baseline_days: int = 28
    trend_min_coverage: float = 0.8  # share of expected daily aggregates present
    trend_min_avg_players: float = 100.0
    trend_growth_weight: float = 0.70
    trend_acceleration_weight: float = 0.30
    # Eligibility (prompt 6 A): no trend scores from a stale source, and none for
    # games whose window is too sparse (trend_min_coverage) or too small
    # (trend_min_avg_players).
    trend_max_staleness_hours: float = 26.0
    trend_min_source_reliability: float = 0.5
    trending_satisfaction_weight: float = 0.80
    trending_trend_weight: float = 0.20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def category_weights(self) -> dict[str, dict[str, float]]:
        return {
            "owned": {
                "satisfaction": self.owned_satisfaction_weight,
                "backlog": self.owned_backlog_weight,
            },
            "unowned": {"satisfaction": self.unowned_satisfaction_weight},
            "trending": {
                "satisfaction": self.trending_satisfaction_weight,
                "trend": self.trending_trend_weight,
            },
        }

    def validate(self) -> EngineParams:
        """Satisfaction must be the main signal of every category ranking (prompt 5 C)."""
        for category, weights in self.category_weights().items():
            if any(w < 0 for w in weights.values()):
                raise ValueError(f"{category} ranking weights must not be negative")
            sat = weights["satisfaction"]
            if sat <= 0 or sat < 0.5 * sum(weights.values()):
                raise ValueError(
                    f"{category} ranking: satisfaction must carry at least half the weight"
                )
        return self

    def with_overrides(self, overrides: dict[str, Any] | None) -> EngineParams:
        """Apply validated overrides; unknown keys or wrong types raise ValueError."""
        if not overrides:
            return self
        known = {f.name: f for f in fields(self)}
        changes: dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in known:
                raise ValueError(f"unknown recommender parameter: {key}")
            current = getattr(self, key)
            if isinstance(current, dict):
                if not isinstance(value, dict):
                    raise ValueError(f"{key} must be an object")
                merged = {**current, **{str(k): float(v) for k, v in value.items()}}
                changes[key] = merged
            elif isinstance(current, bool) or not isinstance(value, int | float):
                raise ValueError(f"{key} must be a number")
            else:
                changes[key] = type(current)(value)
        return replace(self, **changes).validate()


DEFAULT_PARAMS = EngineParams().validate()
