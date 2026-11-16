"""Satisfaction-model features (schema ``sat-v1``), shared by training and serving.

Every feature is computed from a :class:`KnownState` (what was known at the
prediction time) plus catalogue data, never from the outcome being predicted:

==================== ===============================================================
Group                Features
==================== ===============================================================
Content              Match, its confidence, metadata confidence, preference
                     coverage, the five scoring-group scores, positive and negative
                     points (the content engine run on the as-of profile)
Collaborative        Percentile of the game for this player (cross-fitted in
                     training, the deployed model at serving); NaN when unavailable
Category             Owned at the time; category of the context (owned, unowned,
                     trending) one-hot
Exposure             Shown before, impressions before, best position, clicked before
Game                 Review count (log), positive %, age, free, rolled shares of the
                     schema's tag set (the game feature vector)
Similar players      Other players' satisfaction with the game *before* t (count and
                     a shrunk positive rate)
Player               Library size, lifetime and recent hours, prior ratings (count,
                     shrunk mean and positive rate), feedback count, profile
                     confidence, and the player's preference vector on the schema's
                     tag set
==================== ===============================================================

Never features: the target game's own rating, reactions or playtime; any event
after t. Labels are built separately (``labels.py``).
"""

from __future__ import annotations

import bisect
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np

from app.machine_learning.features.history import KnownState
from app.recommendations.features.vectors import (
    GameVector,
    Taxonomy,
    category_shares,
    rollup_shares,
)
from app.recommendations.params import EngineParams
from app.recommendations.profiling.preferences import build_profile
from app.recommendations.ranking.compatibility import Compatibility, Preference, compatibility

FEATURE_SCHEMA_VERSION = "sat-v1"
GROUPS = (
    "genres_and_themes",
    "gameplay_mechanics",
    "game_modes",
    "game_structure",
    "pace_and_complexity",
)
CATEGORIES = ("owned", "unowned", "trending")
TAG_COUNT = 24


@dataclass(frozen=True)
class FeatureSchema:
    version: str
    tag_slugs: tuple[str, ...]

    @property
    def names(self) -> list[str]:
        base = [
            "content_match",
            "content_confidence",
            "metadata_confidence",
            "preference_coverage",
            *(f"group_{g}" for g in GROUPS),
            "positive_points",
            "negative_points",
            "cf_percentile",
            "owned_at_time",
            *(f"category_{c}" for c in CATEGORIES),
            "exposed_before",
            "impressions_before",
            "best_position_before",
            "clicked_before",
            "log_review_count",
            "review_positive_pct",
            "release_age_years",
            "is_free",
            "others_ratings_before",
            "others_positive_rate",
            "user_library_size",
            "user_log_hours",
            "user_recent_hours",
            "user_ratings_before",
            "user_mean_rating_before",
            "user_positive_rate_before",
            "user_feedback_count",
            "user_profile_confidence",
        ]
        return (
            base + [f"game_tag_{s}" for s in self.tag_slugs] + [f"pref_{s}" for s in self.tag_slugs]
        )

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "tag_slugs": list(self.tag_slugs), "names": self.names}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FeatureSchema:
        return cls(str(d["version"]), tuple(d["tag_slugs"]))


def choose_schema(vectors: Mapping[int, GameVector], taxonomy: Taxonomy) -> FeatureSchema:
    """The tag set: the most frequent features in the catalogue (fixed per model)."""
    counts: dict[int, int] = {}
    for vec in vectors.values():
        for fid in vec.features:
            counts[fid] = counts.get(fid, 0) + 1
    top = sorted(counts, key=lambda f: (-counts[f], taxonomy.nodes[f].slug))[:TAG_COUNT]
    return FeatureSchema(FEATURE_SCHEMA_VERSION, tuple(sorted(taxonomy.nodes[f].slug for f in top)))


@dataclass(frozen=True, slots=True)
class GameInfo:
    review_count: int | None
    review_pct: float | None
    release_date: date | None
    is_free: bool


@dataclass(frozen=True, slots=True)
class UserContext:
    """Per (player, time) part: the as-of profile and player features."""

    state: KnownState
    preferences: dict[int, Preference]
    profile_confidence: float
    features: dict[str, float]


@dataclass
class FeatureBuilder:
    taxonomy: Taxonomy
    vectors: Mapping[int, GameVector]
    prevalence: Mapping[int, float]
    params: EngineParams
    games: Mapping[int, GameInfo]
    schema: FeatureSchema
    # game -> [(time, user, rating)] ascending, for "other players before t"
    rating_index: Mapping[int, Sequence[tuple[datetime, uuid.UUID, int]]] = field(
        default_factory=dict
    )
    global_positive_rate: float = 0.5
    _rolled: dict[int, dict[int, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._tag_ids = [
            self.taxonomy.by_slug[s].id for s in self.schema.tag_slugs if s in self.taxonomy.by_slug
        ]
        self.names = self.schema.names

    def rolled(self, gid: int) -> dict[int, float]:
        cached = self._rolled.get(gid)
        if cached is None:
            vec = self.vectors.get(gid)
            cached = (
                rollup_shares(category_shares(vec, self.taxonomy), self.taxonomy) if vec else {}
            )
            self._rolled[gid] = cached
        return cached

    # --- player ---------------------------------------------------------------

    def user_context(self, state: KnownState) -> UserContext:
        result = build_profile(
            state.records, self.vectors, self.prevalence, self.taxonomy, self.params, state.feedback
        )
        prefs = {
            fid: Preference(p.value, p.confidence, recent=p.recent, historical=p.historical)
            for fid, p in result.preferences.items()
        }
        for fid, (value, _excluded) in state.manual.items():
            if value is not None:
                prefs[fid] = Preference(value, 1.0, origin="manual")
        ratings = [r.rating for r in state.ratings]
        n = len(ratings)
        hours = sum((r.lifetime_minutes or 0) for r in state.records if r.owned) / 60.0
        recent = sum((r.recent_minutes or 0) for r in state.records if r.owned) / 60.0
        feats = {
            "user_library_size": float(len(state.owned)),
            "user_log_hours": math.log1p(hours),
            "user_recent_hours": recent,
            "user_ratings_before": float(n),
            # Shrunk towards neutral / the global rate: few ratings say little.
            "user_mean_rating_before": sum(ratings) / (n + 2.0),
            "user_positive_rate_before": (
                sum(1 for r in ratings if r >= 1) + 2 * self.global_positive_rate
            )
            / (n + 2.0),
            "user_feedback_count": float(len(state.feedback)),
            "user_profile_confidence": result.confidence,
        }
        for slug, fid in zip(self.schema.tag_slugs, self._tag_ids, strict=False):
            pref = prefs.get(fid)
            feats[f"pref_{slug}"] = pref.value * pref.confidence if pref else math.nan
        return UserContext(state, prefs, result.confidence, feats)

    # --- pair ------------------------------------------------------------------

    def compat(self, user: UserContext, gid: int) -> Compatibility | None:
        vec = self.vectors.get(gid)
        if vec is None or vec.is_empty:
            return None
        return compatibility(vec, user.preferences, self.taxonomy, self.params)

    def row(
        self,
        user: UserContext,
        gid: int,
        *,
        cf_percentile: float | None,
        category: str | None = None,
        compat: Compatibility | None = None,
    ) -> np.ndarray:
        f: dict[str, float] = dict(user.features)
        compat = compat if compat is not None else self.compat(user, gid)
        if compat is not None:
            f["content_match"] = compat.score
            f["content_confidence"] = compat.confidence
            f["metadata_confidence"] = compat.metadata_confidence
            f["preference_coverage"] = compat.preference_coverage
            scores = {g.group: g.score for g in compat.groups}
            for g in GROUPS:
                s = scores.get(g)
                f[f"group_{g}"] = math.nan if s is None else s
            f["positive_points"] = sum(c.points for c in compat.contributions if c.points > 0)
            f["negative_points"] = sum(c.points for c in compat.contributions if c.points < 0)
        f["cf_percentile"] = math.nan if cf_percentile is None else cf_percentile
        state = user.state
        owned = gid in state.owned or (gid == state.excluded_game and state.target_owned)
        f["owned_at_time"] = float(owned)
        shown = [e for e in state.exposures if e.game_id == gid]
        last_cat = next((e.category for e in reversed(shown) if e.category), None)
        cat = category or last_cat or ("owned" if owned else "unowned")
        for c in CATEGORIES:
            f[f"category_{c}"] = float(cat == c)
        impressions = [e for e in shown if e.event_type == "impression"]
        positions = [e.position for e in shown if e.position]
        f["exposed_before"] = float(bool(shown))
        f["impressions_before"] = float(len(impressions))
        f["best_position_before"] = float(min(positions)) if positions else math.nan
        f["clicked_before"] = float(any(e.event_type != "impression" for e in shown))
        info = self.games.get(gid)
        if info is not None:
            f["log_review_count"] = (
                math.log1p(info.review_count) if info.review_count is not None else math.nan
            )
            f["review_positive_pct"] = info.review_pct if info.review_pct is not None else math.nan
            f["release_age_years"] = (
                (state.at.date() - info.release_date).days / 365.25
                if info.release_date
                else math.nan
            )
            f["is_free"] = float(info.is_free)
        others = self.rating_index.get(gid, ())
        upto = bisect.bisect_left([o[0] for o in others], state.at)
        prior = [r for _, u, r in others[:upto] if u != state.user_id]
        f["others_ratings_before"] = float(len(prior))
        f["others_positive_rate"] = (
            sum(1 for r in prior if r >= 1) + 2 * self.global_positive_rate
        ) / (len(prior) + 2.0)
        rolled = self.rolled(gid)
        for slug, fid in zip(self.schema.tag_slugs, self._tag_ids, strict=False):
            f[f"game_tag_{slug}"] = rolled.get(fid, 0.0)
        return np.array([f.get(n, math.nan) for n in self.names], dtype=np.float64)
