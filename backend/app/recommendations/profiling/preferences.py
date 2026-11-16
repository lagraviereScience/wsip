"""Player preference and confidence vectors (spec §11-§13, §15).

Pure functions: no database, no clock. Inputs are the player's library records,
the game vectors and catalogue prevalence. The output keeps preference strength
(-1..1) and confidence (0..1) separate (spec §15), and keeps the three signal
families apart so that playtime is never mistaken for satisfaction (spec §13):

- **Satisfaction**: explicit ratings (Loved +1 ... Hated -1). The primary signal.
- **Behaviour, historical**: how over-represented a feature is in the player's
  lifetime playtime compared with the catalogue (a lift, log-scaled).
- **Behaviour, recent**: the same lift on recent activity.
- **Feedback**: explicit reactions on recommendation cards (favourite, like, save
  for later, dislike, not my type). Interest evidence: weaker than a rating,
  stronger than playtime. "Not interested" and "already played" carry none.

Behaviour is capped in confidence and in how negative it can go, because playing
little of something is weak evidence of dislike. See docs/RECOMMENDATIONS.md for
the formulas and their rationale.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.recommendations.features.vectors import (
    GameVector,
    Taxonomy,
    categories_present,
    category_shares,
    rollup_shares,
)
from app.recommendations.params import EngineParams


@dataclass(frozen=True, slots=True)
class PlayRecord:
    """One game in the player's library (or rated by them)."""

    game_id: int
    owned: bool = True
    lifetime_minutes: int | None = None  # None = unknown (never invented as 0)
    recent_minutes: int | None = None  # Steam's last-two-weeks value
    days_since_last_play: float | None = None
    rating: int | None = None  # spec §18 scale, -2..2


# Strongest first: when a game carries several reactions, the first one listed
# decides its feature evidence (an explicit negative beats an earlier like).
FEEDBACK_PRIORITY = ("not_my_type", "dislike", "favourite", "like", "save_for_later")


def feedback_signal(kinds: Iterable[str], p: EngineParams) -> tuple[float, float] | None:
    """(value, weight) of a game's reactions, or None when they carry no evidence."""
    present = set(kinds)
    for kind in FEEDBACK_PRIORITY:
        if kind in present and p.feedback_weights.get(kind, 0.0) > 0:
            return p.feedback_values[kind], p.feedback_weights[kind]
    return None


@dataclass(slots=True)
class FeatureEvidence:
    """Accumulators for one feature node."""

    time_hist: float = 0.0  # sum of rolled share * H_total
    time_recent: float = 0.0  # sum of rolled share * recent activity
    exposure: float = 0.0  # sum of rolled share * metadata confidence (owned games)
    exposure_recent: float = 0.0
    rating_sum: float = 0.0
    rating_weight: float = 0.0
    feedback_sum: float = 0.0
    feedback_weight: float = 0.0
    minutes_lifetime: float = 0.0  # attributed raw minutes (display)
    minutes_recent: float = 0.0
    top_games: list[tuple[float, int]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InferredPreference:
    feature_id: int
    value: float  # combined, -1..1
    confidence: float  # 0..1
    historical: float | None
    historical_confidence: float
    recent: float | None
    recent_confidence: float
    satisfaction: float | None
    satisfaction_confidence: float
    feedback: float | None
    feedback_confidence: float
    minutes_lifetime: int
    minutes_recent: int
    evidence_games: tuple[int, ...]  # most influential games, strongest first


@dataclass(frozen=True, slots=True)
class ProfileResult:
    preferences: dict[int, InferredPreference]
    games_considered: int
    games_with_metadata: int
    games_played: int
    games_rated: int
    games_with_feedback: int
    confidence: float  # overall profile confidence, 0..1
    total_minutes: int
    recent_minutes: int


# --- Spec §12 transforms ------------------------------------------------------


def h_total(minutes: int | None, p: EngineParams) -> float:
    if not minutes or minutes <= 0:
        return 0.0
    hours = min(minutes / 60.0, p.lifetime_cap_hours)
    return math.log1p(hours) / math.log1p(p.lifetime_cap_hours)


def h_recent(minutes: int | None, p: EngineParams) -> float:
    if not minutes or minutes <= 0:
        return 0.0
    return 1.0 - math.exp(-(minutes / 60.0) / p.recent_scale_hours)


def recency(days: float | None, p: EngineParams) -> float:
    if days is None:
        return 0.0
    return float(2.0 ** (-max(0.0, days) / p.recency_half_life_days))


def recent_activity(rec: PlayRecord, p: EngineParams) -> float:
    """Recent engagement in [0, 1]: Steam's 2-week playtime, or decayed lifetime play.

    The decayed term lets a game last played three weeks ago still count as a
    recent interest; it uses only values Steam reports (no invented history).
    """
    return max(
        h_recent(rec.recent_minutes, p),
        recency(rec.days_since_last_play, p) * h_total(rec.lifetime_minutes, p),
    )


# --- Catalogue prevalence -------------------------------------------------------


def catalogue_prevalence(vectors: Iterable[GameVector], taxonomy: Taxonomy) -> dict[int, float]:
    """P(f) = mean over catalogue games with any feature in f's category of rolled share(f)."""
    sums: dict[int, float] = defaultdict(float)
    games_per_cat: dict[str, int] = defaultdict(int)
    for vec in vectors:
        for cat in categories_present(vec, taxonomy):
            games_per_cat[cat] += 1
        for fid, share in rollup_shares(category_shares(vec, taxonomy), taxonomy).items():
            sums[fid] += share
    return {
        fid: total / games_per_cat[taxonomy.nodes[fid].category]
        for fid, total in sums.items()
        if games_per_cat.get(taxonomy.nodes[fid].category)
    }


# --- Profile ------------------------------------------------------------------


def _lift_value(share: float, prevalence: float, p: EngineParams) -> float:
    if share <= 0:
        return p.behaviour_min_value
    raw = math.log2(share / prevalence) / p.behaviour_lift_span
    return max(p.behaviour_min_value, min(1.0, raw))


def _evidence_confidence(n: float, k: float, cap: float = 1.0) -> float:
    return cap * (1.0 - math.exp(-max(0.0, n) / k))


def build_profile(
    records: Iterable[PlayRecord],
    vectors: Mapping[int, GameVector],
    prevalence: Mapping[int, float],
    taxonomy: Taxonomy,
    p: EngineParams,
    feedback: Mapping[int, Iterable[str]] | None = None,
) -> ProfileResult:
    """Infer the profile. ``feedback`` maps game id -> current reactions on it."""
    recs = list(records)
    ev: dict[int, FeatureEvidence] = defaultdict(FeatureEvidence)
    cat_time_hist: dict[str, float] = defaultdict(float)
    cat_time_recent: dict[str, float] = defaultdict(float)
    with_meta = played = rated = 0
    total_minutes = recent_minutes_total = 0

    for rec in recs:
        if rec.lifetime_minutes:
            played += 1 if rec.lifetime_minutes > 0 else 0
            total_minutes += rec.lifetime_minutes
        recent_minutes_total += rec.recent_minutes or 0
        if rec.rating is not None:
            rated += 1
        vec = vectors.get(rec.game_id)
        if vec is None or vec.is_empty:
            continue
        with_meta += 1
        shares = category_shares(vec, taxonomy)
        rolled = rollup_shares(shares, taxonomy)
        # Metadata reliability of the game as a whole, for exposure weighting.
        meta_conf = sum(fv.confidence for fv in vec.features.values()) / len(vec.features)
        ht = h_total(rec.lifetime_minutes, p) if rec.owned else 0.0
        ha = recent_activity(rec, p) if rec.owned else 0.0
        for cat in categories_present(vec, taxonomy):
            cat_time_hist[cat] += ht
            cat_time_recent[cat] += ha
        for fid, share in rolled.items():
            e = ev[fid]
            if rec.owned:
                e.time_hist += share * ht
                e.time_recent += share * ha
                e.exposure += share * meta_conf
                if ha > 0:
                    e.exposure_recent += share * meta_conf
                e.minutes_lifetime += share * (rec.lifetime_minutes or 0)
                e.minutes_recent += share * (rec.recent_minutes or 0)
                if ht > 0:
                    e.top_games.append((share * ht, rec.game_id))
            if rec.rating is not None:
                w = share * meta_conf
                e.rating_sum += w * (rec.rating / 2.0)
                e.rating_weight += w
                # Rated games are evidence too; loved ones rank first.
                e.top_games.append((share * (1.0 + rec.rating / 2.0), rec.game_id))

    with_feedback = 0
    for gid, kinds in (feedback or {}).items():
        signal = feedback_signal(kinds, p)
        vec = vectors.get(gid)
        if signal is None or vec is None or vec.is_empty:
            continue
        with_feedback += 1
        value, weight = signal
        rolled = rollup_shares(category_shares(vec, taxonomy), taxonomy)
        meta_conf = sum(fv.confidence for fv in vec.features.values()) / len(vec.features)
        for fid, share in rolled.items():
            e = ev[fid]
            w = share * meta_conf * weight
            e.feedback_sum += w * value
            e.feedback_weight += w
            if value > 0:
                e.top_games.append((share * value, gid))

    prefs: dict[int, InferredPreference] = {}
    for fid, e in ev.items():
        node = taxonomy.nodes[fid]
        prev = prevalence.get(fid, 0.0)
        scoreable = prev >= p.min_catalogue_prevalence

        hist = hist_c = None
        if scoreable and cat_time_hist.get(node.category, 0.0) > 0 and e.exposure > 0:
            hist = _lift_value(e.time_hist / cat_time_hist[node.category], prev, p)
            hist_c = _evidence_confidence(
                e.exposure, p.behaviour_evidence_k, p.behaviour_max_confidence
            )
        rec_v = rec_c = None
        if scoreable and cat_time_recent.get(node.category, 0.0) > 0 and e.exposure > 0:
            rec_v = _lift_value(e.time_recent / cat_time_recent[node.category], prev, p)
            rec_c = _evidence_confidence(
                e.exposure_recent, p.behaviour_evidence_k, p.behaviour_max_confidence
            )
        sat = sat_c = None
        if e.rating_weight > 0:
            sat = e.rating_sum / (e.rating_weight + p.satisfaction_prior_weight)
            sat_c = _evidence_confidence(e.rating_weight, p.satisfaction_evidence_k)

        fb = fb_c = None
        if e.feedback_weight > 0:
            fb = e.feedback_sum / (e.feedback_weight + p.feedback_prior_weight)
            fb_c = _evidence_confidence(e.feedback_weight, p.feedback_evidence_k)

        # Behaviour = blend of historical and recent lifts (whichever exist).
        b_parts = [
            (v, c, w)
            for v, c, w in ((hist, hist_c, 1.0 - p.recent_blend), (rec_v, rec_c, p.recent_blend))
            if v is not None and c is not None and c > 0
        ]
        b = b_c = None
        if b_parts:
            wsum = sum(c * w for _, c, w in b_parts)
            b = sum(v * c * w for v, c, w in b_parts) / wsum
            b_c = max(c for _, c, _ in b_parts)

        parts = [
            (v, c, w)
            for v, c, w in (
                (sat, sat_c, p.satisfaction_weight),
                (fb, fb_c, p.feedback_weight),
                (b, b_c, p.behaviour_weight),
            )
            if v is not None and c is not None and c > 0
        ]
        if not parts:
            continue
        wsum = sum(c * w for _, c, w in parts)
        value = sum(v * c * w for v, c, w in parts) / wsum
        miss = 1.0
        for _, c, _ in parts:
            miss *= 1.0 - c
        top = tuple(gid for _, gid in sorted(e.top_games, key=lambda t: (-t[0], t[1]))[:3])
        prefs[fid] = InferredPreference(
            feature_id=fid,
            value=round(max(-1.0, min(1.0, value)), 4),
            confidence=round(1.0 - miss, 4),
            historical=None if hist is None else round(hist, 4),
            historical_confidence=round(hist_c or 0.0, 4),
            recent=None if rec_v is None else round(rec_v, 4),
            recent_confidence=round(rec_c or 0.0, 4),
            satisfaction=None if sat is None else round(sat, 4),
            satisfaction_confidence=round(sat_c or 0.0, 4),
            feedback=None if fb is None else round(fb, 4),
            feedback_confidence=round(fb_c or 0.0, 4),
            minutes_lifetime=round(e.minutes_lifetime),
            minutes_recent=round(e.minutes_recent),
            evidence_games=top,
        )

    # Overall confidence: how much the profile has to go on (played games with
    # metadata, plus ratings, which count more).
    played_with_meta = sum(
        1
        for r in recs
        if (r.lifetime_minutes or 0) > 0
        and r.game_id in vectors
        and not vectors[r.game_id].is_empty
    )
    overall = 1.0 - math.exp(-(played_with_meta + 2.0 * rated + with_feedback) / 15.0)
    return ProfileResult(
        preferences=prefs,
        games_considered=len(recs),
        games_with_metadata=with_meta,
        games_played=played,
        games_rated=rated,
        games_with_feedback=with_feedback,
        confidence=round(overall, 4),
        total_minutes=total_minutes,
        recent_minutes=recent_minutes_total,
    )
