"""Recommendation generation for the three categories (spec §19, §20).

Candidate generation and ranking are separate steps:

1. ``*_candidates`` pick eligible games (ownership, exclusions, quality floors).
2. ``_rank`` scores every candidate with the content-based compatibility and the
   category formula, and builds explanations from the score contributions.

Exclusions are applied before ranking and are hard constraints (spec §11, §19).
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.recommendation import RecommendationRun
from app.recommendations.engines import (
    ScoringEngine,
    ScoringMode,
    active_engine,
    config_version,
)
from app.recommendations.features.vectors import (
    GameVector,
    Taxonomy,
    category_shares,
    excluded_by,
    rollup_shares,
)
from app.recommendations.params import PARAMS_VERSION, EngineParams
from app.recommendations.profiling.preferences import PlayRecord
from app.recommendations.ranking import explain
from app.recommendations.ranking.compatibility import Compatibility, compatibility
from app.recommendations.ranking.scores import (
    TrendInput,
    backlog_score,
    category_score,
    owned_score,
    trend_metrics,
    trend_scores,
    trending_score,
)
from app.repositories import behaviour as behaviour_repo
from app.repositories import recommendation as repo
from app.services.profile import PLATFORM, EffectivePreferences, effective_preferences

if TYPE_CHECKING:
    from app.recommendations.candidate_generation.collaborative import CollaborativeScorer
    from app.recommendations.ranking.satisfaction import SatisfactionScorer

logger = logging.getLogger(__name__)

ALGORITHM = PARAMS_VERSION  # content-based; "+<cf version>" when a CF model is blended
MAX_FAVOURITES = 10
CF_CANDIDATES = 100  # extra unowned candidates taken from the collaborative model
CF_REASON_MIN_PERCENTILE = 90.0
CF_REASON_MIN_WEIGHT = 0.1
MIN_FAVOURITE_MINUTES = 10 * 60
LIMITS = {"owned": 60, "unowned": 60, "trending": 40}  # items stored per run


@dataclass(slots=True)
class Context:
    user_id: uuid.UUID
    taxonomy: Taxonomy
    effective: EffectivePreferences
    params: EngineParams
    now: datetime
    profile_run_id: int | None
    mode: ScoringMode = ScoringMode.CLASSIC
    records: dict[int, PlayRecord] = field(default_factory=dict)
    # Explicit negatives and "already played": never recommended (hard filter).
    hidden: set[int] = field(default_factory=set)
    favourite_ids: list[int] = field(default_factory=list)
    collaborative: CollaborativeScorer | None = None
    satisfaction: SatisfactionScorer | None = None
    _rolled: dict[int, dict[int, float]] = field(default_factory=dict)

    def rolled(self, vec: GameVector) -> dict[int, float]:
        cached = self._rolled.get(vec.game_id)
        if cached is None:
            cached = rollup_shares(category_shares(vec, self.taxonomy), self.taxonomy)
            self._rolled[vec.game_id] = cached
        return cached


def load_context(
    session: Session,
    user_id: uuid.UUID,
    params: EngineParams,
    now: datetime,
    *,
    engine: ScoringEngine | None = None,
) -> Context:
    """Everything the generators need. ``engine`` defaults to the deployment's mode
    (AI_GRADE, app.recommendations.engines); it decides which trained scorers, if
    any, are used. Everything else is identical in both modes."""
    engine = engine or active_engine()
    run = repo.latest_profile_run(session, user_id)
    records = {r.game_id: r for r in repo.play_records(session, user_id, PLATFORM, now)}
    reactions = behaviour_repo.reactions(session, user_id)
    favourites = sorted(
        (r for r in reactions.values() if r.favourite), key=lambda r: (r.updated_at, r.game_id)
    )
    scorers = engine.scorers(session, user_id, params, now)
    return Context(
        user_id=user_id,
        taxonomy=repo.load_taxonomy(session),
        effective=effective_preferences(session, user_id),
        params=params,
        now=now,
        profile_run_id=run.id if run else None,
        mode=engine.mode,
        records=records,
        hidden=behaviour_repo.hidden_game_ids(session, user_id),
        favourite_ids=[r.game_id for r in reversed(favourites)],
        collaborative=scorers.collaborative,
        satisfaction=scorers.satisfaction,
    )


def _compat(ctx: Context, vec: GameVector) -> Compatibility:
    return compatibility(vec, ctx.effective.preferences, ctx.taxonomy, ctx.params)


def _match(ctx: Context, game_id: int, compat: Compatibility) -> tuple[float, float | None]:
    """Content Match, blended with the collaborative percentile when a model applies."""
    if ctx.collaborative is None:
        return compat.score, None
    blended, pct = ctx.collaborative.blend(compat.score, game_id)
    return round(blended, 2), pct


def _collaborative_reasons(ctx: Context, pct: float | None) -> list[explain.Reason]:
    cf = ctx.collaborative
    if cf is None or pct is None or cf.weight < CF_REASON_MIN_WEIGHT:
        return []
    return [explain.collaborative_reason(pct)] if pct >= CF_REASON_MIN_PERCENTILE else []


def _excluded(ctx: Context, vec: GameVector) -> bool:
    return bool(
        ctx.effective.excluded
        and excluded_by(vec, ctx.effective.excluded, ctx.taxonomy, ctx.params.exclusion_min_value)
    )


def _contribution_dicts(ctx: Context, compat: Compatibility) -> list[dict[str, Any]]:
    out = []
    for c in compat.contributions:
        node = ctx.taxonomy.nodes[c.feature_id]
        out.append(
            {
                "feature": node.slug,
                "name": node.name,
                "group": c.group,
                "game_features": [ctx.taxonomy.nodes[f].slug for f in c.game_feature_ids],
                "preference": round(c.preference, 3),
                "preference_confidence": round(c.preference_confidence, 3),
                "origin": c.origin,
                "game_value": c.game_value,
                "metadata_confidence": c.metadata_confidence,
                "points": round(c.points, 3),
            }
        )
    return out


def _item(
    ctx: Context,
    vec: GameVector,
    compat: Compatibility,
    score: float,
    reasons: list[explain.Reason],
    sources: list[str],
    *,
    backlog: float | None = None,
    trend: float | None = None,
    collaborative: float | None = None,
) -> dict[str, Any]:
    return {
        "game_id": vec.game_id,
        "score": round(score, 2),
        "satisfaction_score": compat.score,
        "backlog_score": backlog,
        "trend_score": trend,
        "collaborative_score": collaborative,
        "predicted_satisfaction": None,
        "_compat": compat,
        "confidence": compat.confidence,
        "metadata_confidence": compat.metadata_confidence,
        "group_scores": [asdict(g) for g in compat.groups],
        "contributions": _contribution_dicts(ctx, compat),
        "reasons": [r.to_dict() for r in reasons],
        "candidate_sources": sources,
    }


def _feature_reasons(ctx: Context, compat: Compatibility) -> list[explain.Reason]:
    reasons = explain.feature_reasons(compat, ctx.taxonomy, ctx.effective.recent)
    if not compat.contributions:
        reasons.append(explain.no_preference_reason())
    return reasons


def _finish(
    session: Session,
    ctx: Context,
    category: str,
    items: list[dict[str, Any]],
    considered: int,
    excluded: int,
    *,
    data_state: str = "ok",
    note: str | None = None,
) -> RecommendationRun:
    sat = (
        ctx.satisfaction
        if items and ctx.satisfaction and ctx.satisfaction.enabled(category)
        else None
    )
    if sat is not None:
        try:
            predicted = sat.predict(
                category, [(i["game_id"], i["_compat"], i["collaborative_score"]) for i in items]
            )
        except Exception:
            logger.exception("satisfaction prediction failed; ranking on Match")
            sat = None
        else:
            # Global satisfaction is the main signal; category weights add the rest.
            for item, prob in zip(items, predicted, strict=True):
                item["predicted_satisfaction"] = round(float(prob), 4)
                item["score"] = round(
                    category_score(
                        category,
                        100.0 * float(prob),
                        ctx.params,
                        backlog=item["backlog_score"],
                        trend=item["trend_score"],
                    ),
                    2,
                )
    for item in items:
        item.pop("_compat", None)
    items.sort(key=lambda i: (-i["score"], -i["confidence"], i["game_id"]))
    cf = ctx.collaborative
    algorithm = ALGORITHM
    if cf is not None:
        algorithm += f"+cf#{cf.model_version_id}"
    if sat is not None:
        algorithm += f"+sat#{sat.model_version_id}"
    run = RecommendationRun(
        user_id=ctx.user_id,
        category=category,
        status="succeeded",
        data_state=data_state,
        algorithm=algorithm,
        scoring_mode=ctx.mode.value,
        config_version=config_version(ctx.params, ctx.mode),
        model_version_id=cf.model_version_id if cf else None,
        satisfaction_model_version_id=sat.model_version_id if sat else None,
        params=ctx.params.to_dict(),
        profile_run_id=ctx.profile_run_id,
        candidates_considered=considered,
        candidates_excluded=excluded,
        note=note,
    )
    return repo.save_recommendation_run(session, run, items[: LIMITS[category]])


# --- Owned (spec §20.1) -----------------------------------------------------------


def generate_owned(session: Session, ctx: Context) -> RecommendationRun:
    p = ctx.params
    owned = {gid: r for gid, r in ctx.records.items() if r.owned}
    meta = repo.game_meta(session, owned)
    vectors = repo.load_game_vectors(session, owned)
    items: list[dict[str, Any]] = []
    excluded = no_metadata = already_known = 0
    for gid, rec in owned.items():
        if gid in ctx.hidden:
            excluded += 1
            continue
        m = meta.get(gid)
        if m is None or m["game_type"] != "game":
            continue
        vec = vectors.get(gid)
        if vec is None or vec.is_empty:
            no_metadata += 1
            continue
        if _excluded(ctx, vec):
            excluded += 1
            continue
        hours = (rec.lifetime_minutes or 0) / 60.0
        recently = (rec.recent_minutes or 0) > 0 or (
            rec.days_since_last_play is not None
            and rec.days_since_last_play < p.owned_exclude_recent_days
        )
        if hours >= p.owned_exclude_min_hours or (recently and hours > 0):
            already_known += 1  # heavily played or currently playing: not "play next"
            continue
        compat = _compat(ctx, vec)
        match, pct = _match(ctx, gid, compat)
        backlog = backlog_score(rec.lifetime_minutes, rec.days_since_last_play, p)
        reasons = explain.owned_reasons(rec.lifetime_minutes, rec.days_since_last_play)
        reasons += _collaborative_reasons(ctx, pct)
        reasons += _feature_reasons(ctx, compat)
        items.append(
            _item(
                ctx,
                vec,
                compat,
                owned_score(match, backlog, p),
                reasons,
                ["library", *(["collaborative"] if pct is not None else [])],
                backlog=backlog,
                collaborative=pct,
            )
        )
    note = (
        f"{already_known} heavily played or currently played games and "
        f"{no_metadata} games without store metadata were not ranked."
    )
    return _finish(session, ctx, "owned", items, len(owned), excluded, note=note)


# --- Unowned (spec §20.2) -------------------------------------------------------


def _favourites(ctx: Context, vectors: Mapping[int, GameVector]) -> list[tuple[int, str]]:
    """Seeds for "Similar to ...": favourites, then loved games, then most played.

    Returns (game_id, "favourite" | "loved" | "liked" | "played")."""
    out = [(g, "favourite") for g in ctx.favourite_ids if g in vectors][:MAX_FAVOURITES]
    rated = sorted(
        (r for r in ctx.records.values() if (r.rating or 0) >= 1 and r.game_id in vectors),
        key=lambda r: (-(r.rating or 0), -(r.lifetime_minutes or 0), r.game_id),
    )
    taken = {g for g, _ in out}
    out += [
        (r.game_id, "loved" if (r.rating or 0) >= 2 else "liked")
        for r in rated
        if r.game_id not in taken
    ][: MAX_FAVOURITES - len(out)]
    if len(out) < MAX_FAVOURITES:
        played = sorted(
            (
                r
                for r in ctx.records.values()
                if r.owned
                and (r.lifetime_minutes or 0) >= MIN_FAVOURITE_MINUTES
                and (r.rating is None or r.rating >= 0)
                and r.game_id in vectors
                and r.game_id not in {g for g, _ in out}
            ),
            key=lambda r: (-(r.lifetime_minutes or 0), r.game_id),
        )
        out += [(r.game_id, "played") for r in played[: MAX_FAVOURITES - len(out)]]
    return out


def _cosine(a: Mapping[int, float], b: Mapping[int, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def unowned_candidates(session: Session, ctx: Context) -> tuple[dict[int, GameVector], int]:
    """Catalogue games the player neither owns nor has rated, above the quality floor,
    plus the collaborative model's top games for this user (candidate union, §19).
    Explicitly rejected and "already played" games are never candidates."""
    known = set(ctx.records) | ctx.hidden
    catalogue = repo.load_game_vectors(session)
    ids = [gid for gid in catalogue if gid not in known]
    reviews = repo.review_counts(session, ids)
    eligible = {
        gid: catalogue[gid]
        for gid in ids
        if reviews.get(gid, 0) >= ctx.params.unowned_min_reviews and not catalogue[gid].is_empty
    }
    if ctx.collaborative is not None:
        for gid in ctx.collaborative.top(CF_CANDIDATES, exclude=known):
            vec = catalogue.get(gid)
            if vec is not None and not vec.is_empty:
                eligible.setdefault(gid, vec)
    return eligible, len(ids)


def generate_unowned(session: Session, ctx: Context) -> RecommendationRun:
    p = ctx.params
    candidates, considered = unowned_candidates(session, ctx)
    library_vectors = repo.load_game_vectors(session, set(ctx.records) | set(ctx.favourite_ids))
    favourites = _favourites(ctx, library_vectors)
    fav_rolled = [(gid, why, ctx.rolled(library_vectors[gid])) for gid, why in favourites]
    names = {
        gid: m["name"] for gid, m in repo.game_meta(session, [g for g, _ in favourites]).items()
    }
    sources_by_game = repo.discovery_sources(session, candidates)
    items: list[dict[str, Any]] = []
    excluded = 0
    for gid, vec in candidates.items():
        if _excluded(ctx, vec):
            excluded += 1
            continue
        compat = _compat(ctx, vec)
        match, pct = _match(ctx, gid, compat)
        sources = ["content", *sources_by_game.get(gid, [])]
        if pct is not None:
            sources.append("collaborative")
        reasons = _collaborative_reasons(ctx, pct) + _feature_reasons(ctx, compat)
        if fav_rolled:
            rolled = ctx.rolled(vec)
            sim, fav_id, why = max(
                ((_cosine(rolled, fr), fid, w) for fid, w, fr in fav_rolled),
                key=lambda t: (t[0], -t[1]),
            )
            if sim >= p.similar_min_cosine and fav_id in names:
                sources.append(f"similar:{fav_id}")
                reasons.insert(0, explain.similar_reason(names[fav_id], why))
        score = category_score("unowned", match, p)
        items.append(_item(ctx, vec, compat, score, reasons, sources, collaborative=pct))
    return _finish(session, ctx, "unowned", items, considered, excluded)


# --- Trending (spec §20.3) -------------------------------------------------------


def trend_window_days(p: EngineParams) -> int:
    return 2 * p.trend_short_days + p.trend_baseline_days


def generate_trending(session: Session, ctx: Context) -> RecommendationRun:
    p = ctx.params
    need = trend_window_days(p)
    status = repo.player_count_source_status(session, ctx.now)
    fresh = status["freshness_hours"]
    if fresh is not None and fresh > p.trend_max_staleness_hours:
        # The source stopped answering: pause trends rather than score old data.
        # Owned and unowned lists are generated independently and are unaffected.
        note = (
            f"Player-count source is stale: last successful sample {fresh:.0f} h ago "
            f"(limit {p.trend_max_staleness_hours:.0f} h). Trend scores are paused."
        )
        return _finish(session, ctx, "trending", [], 0, 0, data_state="unavailable", note=note)
    rel = status["reliability_7d"]
    if rel is not None and rel < p.trend_min_source_reliability:
        note = (
            f"Player-count source unreliable: {rel:.0%} of calls answered in 7 days "
            f"(minimum {p.trend_min_source_reliability:.0%}). Trend scores are paused."
        )
        return _finish(session, ctx, "trending", [], 0, 0, data_state="unavailable", note=note)
    first_day, days_with_data, tracked = repo.player_count_coverage(session)
    if days_with_data < need:
        since = first_day.isoformat() if first_day else "not started"
        note = (
            f"Trend scores need {need} days of player-count history; "
            f"{days_with_data} collected (since {since}, {tracked} games tracked)."
        )
        return _finish(session, ctx, "trending", [], 0, 0, data_state="unavailable", note=note)

    last_day = ctx.now.date() - timedelta(days=1)  # complete days only
    first = last_day - timedelta(days=need - 1)
    series = repo.daily_player_series(session, first, last_day, min_samples_per_day=4)
    metrics = [
        m for gid, s in series.items() if (m := trend_metrics(TrendInput(gid, s), p)) is not None
    ]
    if not metrics:
        return _finish(
            session,
            ctx,
            "trending",
            [],
            len(series),
            0,
            data_state="incomplete",
            note="Not enough complete player-count history passed the data-quality checks.",
        )
    scores = trend_scores(metrics, p)
    owned = {gid for gid, r in ctx.records.items() if r.owned}
    vectors = repo.load_game_vectors(session, [m.game_id for m in metrics])
    items: list[dict[str, Any]] = []
    excluded = 0
    by_id = {m.game_id: m for m in metrics}
    for gid, trend in scores.items():
        vec = vectors.get(gid)
        if gid in owned or vec is None or vec.is_empty:
            continue
        if gid in ctx.hidden or _excluded(ctx, vec):
            excluded += 1
            continue
        compat = _compat(ctx, vec)
        match, pct = _match(ctx, gid, compat)
        m = by_id[gid]
        growth_pct = (math.exp(m.growth) - 1) * 100
        growth = explain.Reason(
            "trend_growth", f"Players up {growth_pct:.0f}% vs the previous four weeks", "info"
        )
        reasons = [growth, *_collaborative_reasons(ctx, pct), *_feature_reasons(ctx, compat)]
        items.append(
            _item(
                ctx,
                vec,
                compat,
                trending_score(match, trend, p),
                reasons,
                ["player_counts"],
                trend=trend,
                collaborative=pct,
            )
        )
    state = "ok" if items else "incomplete"
    return _finish(session, ctx, "trending", items, len(series), excluded, data_state=state)


GENERATORS = {"owned": generate_owned, "unowned": generate_unowned, "trending": generate_trending}


def generate_all(
    session: Session,
    user_id: uuid.UUID,
    params: EngineParams,
    now: datetime,
    categories: Iterable[str] = ("owned", "unowned", "trending"),
    *,
    engine: ScoringEngine | None = None,
) -> dict[str, RecommendationRun]:
    """Build and store all lists with one engine (default: the active AI_GRADE mode)."""
    categories = tuple(categories)
    started = time.perf_counter()
    ctx = load_context(session, user_id, params, now, engine=engine)
    context_ms = (time.perf_counter() - started) * 1000
    runs: dict[str, RecommendationRun] = {}
    for c in categories:
        t0 = time.perf_counter()
        run = GENERATORS[c](session, ctx)
        # Generation time incl. a share of the shared context load (monitoring).
        run.duration_ms = round((time.perf_counter() - t0) * 1000 + context_ms / len(categories))
        runs[c] = run
    return runs


def popular_now(session: Session, ctx: Context, limit: int = 12) -> list[dict[str, Any]]:
    """Most concurrent players in the latest self-collected sample, personalised by match.

    Absolute popularity, explicitly NOT a trend (spec §20.3); shown while trend data
    accumulates. Owned and excluded games are left out."""
    rows = session.execute(
        text(
            """
            SELECT s.game_id, s.player_count, s.sampled_at
              FROM player_count_samples s
             WHERE s.sampled_at = (SELECT max(sampled_at) FROM player_count_samples)
             ORDER BY s.player_count DESC
             LIMIT 200
            """
        )
    ).all()
    owned = {gid for gid, r in ctx.records.items() if r.owned}
    ids = [int(r[0]) for r in rows if int(r[0]) not in owned]
    vectors = repo.load_game_vectors(session, ids)
    out: list[dict[str, Any]] = []
    for gid, players, sampled_at in rows:
        vec = vectors.get(int(gid))
        if (
            vec is None
            or vec.is_empty
            or int(gid) in owned
            or int(gid) in ctx.hidden
            or _excluded(ctx, vec)
        ):
            continue
        compat = _compat(ctx, vec)
        out.append(
            {
                "game_id": int(gid),
                "players": int(players),
                "sampled_at": sampled_at,
                "satisfaction_score": compat.score,
                "confidence": compat.confidence,
                "reasons": [r.to_dict() for r in _feature_reasons(ctx, compat)],
            }
        )
        if len(out) >= limit:
            break
    return out
