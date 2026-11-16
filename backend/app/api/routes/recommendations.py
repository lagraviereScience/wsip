"""Gamer profile, manual preferences and recommendations for the signed-in user."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import text

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.database.redis import get_redis
from app.models.activity import UserFeedback
from app.models.catalogue import FeatureCategory
from app.recommendations.engines import ScoringMode, active_mode, config_version, engine_for
from app.repositories import behaviour as behaviour_repo
from app.repositories import recommendation as repo
from app.schemas.feedback import GameFeedbackOut
from app.schemas.recommendation import (
    ContributionOut,
    EvidenceGameOut,
    FeatureHistoryPointOut,
    FeaturePreferenceOut,
    GroupScoreOut,
    InferredOut,
    ManualOut,
    ModeBalanceOut,
    PopularNowOut,
    PreferenceEventOut,
    PreferenceHistoryOut,
    PreferenceIn,
    PriceOut,
    ProfileOut,
    ProfileRunOut,
    ReasonOut,
    RecommendationOut,
    RecommendationRunOut,
    RecommendationsOut,
    ReviewOut,
    TrendStatusOut,
    confidence_label,
)
from app.services import profile as profile_service
from app.services import recommendations as rec_service
from app.workers.tasks import refresh_recommendations

router = APIRouter(prefix="/me", tags=["recommendations"])

Category = Literal["owned", "unowned", "trending"]
REFRESH_COOLDOWN_S = 60
PREFERENCE_DEBOUNCE_S = 5


def _queue_refresh(user_id: str, *, discover: bool, cooldown: int, countdown: int = 0) -> bool:
    """Queue a profile + recommendations rebuild unless one was queued very recently."""
    if not get_redis().set(f"refresh:user:{user_id}", "1", nx=True, ex=cooldown):
        return False
    refresh_recommendations.apply_async(
        args=[user_id], kwargs={"discover": discover}, countdown=countdown
    )
    return True


def _evidence_games(db: DbSession, user_id: Any, game_ids: set[int]) -> dict[int, EvidenceGameOut]:
    if not game_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT g.id, g.name, g.capsule_image_url, l.playtime_forever_minutes, f.rating
              FROM games g
              LEFT JOIN user_library l ON l.game_id = g.id AND l.user_id = :u
                   AND l.removed_at IS NULL
              LEFT JOIN user_feedback f ON f.game_id = g.id AND f.user_id = :u
             WHERE g.id = ANY(:ids)
            """
        ),
        {"u": user_id, "ids": list(game_ids)},
    ).all()
    return {
        int(r[0]): EvidenceGameOut(
            game_id=int(r[0]),
            name=r[1],
            capsule_image_url=r[2],
            playtime_minutes=r[3],
            rating=r[4],
        )
        for r in rows
    }


# --- Profile -----------------------------------------------------------------------


@router.get("/profile", response_model=ProfileOut)
def get_profile(db: DbSession, user: CurrentUser) -> ProfileOut:
    taxonomy = repo.load_taxonomy(db)
    cat_names: dict[str, str] = dict(
        db.execute(text("SELECT slug, name FROM feature_categories")).all()
    )
    run = repo.latest_profile_run(db, user.id)
    if run is None:
        _queue_refresh(str(user.id), discover=True, cooldown=REFRESH_COOLDOWN_S)
    inferred = {p.feature_id: p for p in repo.inferred_preferences(db, user.id)}
    manual = {m.feature_id: m for m in repo.manual_preferences(db, user.id)}
    evidence_ids = {g for p in inferred.values() for g in p.evidence_game_ids}
    games = _evidence_games(db, user.id, evidence_ids)

    features: list[FeaturePreferenceOut] = []
    influence: dict[int, float] = defaultdict(float)
    for fid in inferred.keys() | manual.keys():
        node = taxonomy.nodes.get(fid)
        if node is None:
            continue
        inf, man = inferred.get(fid), manual.get(fid)
        if man is not None and man.value is not None:
            value, conf, origin = man.value, 1.0, "manual"
        elif inf is not None:
            value, conf, origin = inf.value, inf.confidence, "inferred"
        else:
            value, conf, origin = None, 0.0, None
        if inf is not None:
            for pos, gid in enumerate(inf.evidence_game_ids):
                influence[gid] += abs(inf.value) * inf.confidence * (1.0, 0.6, 0.3)[min(pos, 2)]
        parent = taxonomy.nodes.get(node.parent_id) if node.parent_id else None
        features.append(
            FeaturePreferenceOut(
                slug=node.slug,
                name=node.name,
                category=node.category,
                category_name=cat_names.get(node.category, node.category),
                group=node.group,
                parent=parent.slug if parent else None,
                value=value,
                confidence=round(conf, 4),
                origin=origin,
                excluded=bool(man and man.excluded),
                inferred=InferredOut(
                    value=inf.value,
                    confidence=inf.confidence,
                    historical=inf.historical,
                    historical_confidence=inf.historical_confidence,
                    recent=inf.recent,
                    recent_confidence=inf.recent_confidence,
                    satisfaction=inf.satisfaction,
                    satisfaction_confidence=inf.satisfaction_confidence,
                    feedback=inf.feedback,
                    feedback_confidence=inf.feedback_confidence,
                )
                if inf
                else None,
                manual=ManualOut(value=man.value, excluded=man.excluded, updated_at=man.updated_at)
                if man
                else None,
                minutes_lifetime=inf.minutes_lifetime if inf else 0,
                minutes_recent=inf.minutes_recent if inf else 0,
                evidence=[games[g] for g in (inf.evidence_game_ids if inf else []) if g in games],
            )
        )
    features.sort(key=lambda f: (-(abs(f.value or 0) * f.confidence), f.slug))

    def minutes(slug: str) -> int:
        node = taxonomy.by_slug.get(slug)
        pref = inferred.get(node.id) if node else None
        return int(pref.minutes_lifetime) if pref else 0

    single, multi = minutes("singleplayer"), minutes("multiplayer")
    top_games = sorted(influence.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    return ProfileOut(
        status="ready" if run else "pending",
        run=ProfileRunOut.model_validate(run, from_attributes=True) if run else None,
        features=features,
        mode_balance=ModeBalanceOut(
            singleplayer_minutes=single,
            multiplayer_minutes=multi,
            singleplayer_share=round(single / (single + multi), 4) if single + multi else None,
        ),
        influential_games=[games[g] for g, _ in top_games if g in games],
    )


def _feature_out_after_change(db: DbSession, user: CurrentUser, slug: str) -> FeaturePreferenceOut:
    profile = get_profile(db, user)
    match = next((f for f in profile.features if f.slug == slug), None)
    if match is not None:
        return match
    taxonomy = repo.load_taxonomy(db)
    node = taxonomy.by_slug[slug]
    category = db.query(FeatureCategory).filter(FeatureCategory.slug == node.category).one()
    return FeaturePreferenceOut(
        slug=node.slug,
        name=node.name,
        category=node.category,
        category_name=category.name,
        group=node.group,
        parent=None,
        value=None,
        confidence=0.0,
        origin=None,
        excluded=False,
        inferred=None,
        manual=None,
        minutes_lifetime=0,
        minutes_recent=0,
        evidence=[],
    )


@router.put("/preferences/{slug}", response_model=FeaturePreferenceOut)
def set_preference(
    db: DbSession,
    user: CurrentUser,
    slug: Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")],
    body: PreferenceIn,
) -> FeaturePreferenceOut:
    """Set a manual preference value and/or a hard exclusion for one canonical feature."""
    try:
        profile_service.set_preference(
            db,
            repo.load_taxonomy(db),
            user.id,
            slug,
            value=body.value,
            excluded=body.excluded,
            now=datetime.now(UTC),
        )
    except profile_service.UnknownFeature as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown feature") from exc
    db.commit()
    _queue_refresh(
        str(user.id),
        discover=False,
        cooldown=PREFERENCE_DEBOUNCE_S,
        countdown=PREFERENCE_DEBOUNCE_S,
    )
    return _feature_out_after_change(db, user, slug)


@router.delete("/preferences/{slug}", response_model=FeaturePreferenceOut)
def clear_preference(
    db: DbSession,
    user: CurrentUser,
    slug: Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")],
) -> FeaturePreferenceOut:
    """Remove the manual value and exclusion; the inferred value applies again."""
    return set_preference(db, user, slug, PreferenceIn(value=None, excluded=False))


@router.get("/preferences/history", response_model=PreferenceHistoryOut)
def preference_history(
    db: DbSession,
    user: CurrentUser,
    feature: Annotated[str | None, Query(max_length=100, pattern=r"^[a-z0-9-]+$")] = None,
) -> PreferenceHistoryOut:
    taxonomy = repo.load_taxonomy(db)
    events = [
        PreferenceEventOut(
            feature=taxonomy.nodes[e.feature_id].slug,
            name=taxonomy.nodes[e.feature_id].name,
            old_value=e.old_value,
            new_value=e.new_value,
            old_excluded=e.old_excluded,
            new_excluded=e.new_excluded,
            created_at=e.created_at,
        )
        for e in repo.preference_events(db, user.id)
        if e.feature_id in taxonomy.nodes
    ]
    out = PreferenceHistoryOut(manual_changes=events)
    if feature is not None:
        node = taxonomy.by_slug.get(feature)
        if node is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown feature")
        out.feature = feature
        out.inferred_history = [
            FeatureHistoryPointOut(
                computed_at=at,
                value=h.value,
                confidence=h.confidence,
                historical=h.historical,
                recent=h.recent,
                satisfaction=h.satisfaction,
            )
            for at, h in repo.preference_history(db, user.id, node.id)
        ]
    return out


# --- Recommendations ---------------------------------------------------------------


def _item_out(
    row: dict[str, Any], tags: list[str], country: str, feedback: GameFeedbackOut | None
) -> RecommendationOut:
    price = None
    if row["price_fetched_at"] is not None:
        price = PriceOut(
            is_free=bool(row["price_is_free"]),
            final_cents=row["final_price_cents"],
            original_cents=row["original_price_cents"],
            discount_pct=row["discount_pct"],
            formatted_final=row["formatted_final_price"],
            formatted_original=row["formatted_original_price"],
            country=country,
            fetched_at=row["price_fetched_at"],
        )
    review = None
    if row["review_count"] is not None or row["review_label"] is not None:
        review = ReviewOut(
            count=row["review_count"],
            percent_positive=row["percent_positive"],
            label=row["review_label"],
        )
    return RecommendationOut(
        rank=row["rank"],
        game_id=row["game_id"],
        name=row["name"],
        steam_appid=row["steam_appid"],
        header_image_url=row["header_image_url"],
        capsule_image_url=row["capsule_image_url"],
        short_description=row["short_description"],
        release_date=row["release_date"],
        owned=bool(row["owned"]),
        playtime_minutes=row["playtime_forever_minutes"],
        last_played_at=row["last_played_at"],
        score=row["score"],
        satisfaction_score=row["satisfaction_score"],
        backlog_score=row["backlog_score"],
        trend_score=row["trend_score"],
        confidence=row["confidence"],
        confidence_label=confidence_label(row["confidence"]),
        metadata_confidence=row["metadata_confidence"],
        group_scores=[GroupScoreOut(**g) for g in row["group_scores"]],
        contributions=[ContributionOut(**c) for c in row["contributions"]],
        reasons=[ReasonOut(**r) for r in row["reasons"]],
        candidate_sources=row["candidate_sources"],
        tags=tags,
        review=review,
        price=price,
        collaborative_score=row["collaborative_score"],
        predicted_satisfaction=row["predicted_satisfaction"],
        feedback=feedback,
    )


def _top_feature_names(
    db: DbSession, game_ids: list[int], per_game: int = 5
) -> dict[int, list[str]]:
    if not game_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT v.game_id, f.name
              FROM (SELECT game_id, feature_id, MAX(value * confidence) AS s,
                           row_number() OVER (PARTITION BY game_id
                                              ORDER BY MAX(value * confidence) DESC, feature_id) rn
                      FROM game_feature_values WHERE game_id = ANY(:ids)
                     GROUP BY game_id, feature_id) v
              JOIN game_features f ON f.id = v.feature_id
             WHERE v.rn <= :n
             ORDER BY v.game_id, v.rn
            """
        ),
        {"ids": game_ids, "n": per_game},
    )
    out: dict[int, list[str]] = defaultdict(list)
    for gid, name in rows:
        out[int(gid)].append(name)
    return out


@router.get("/recommendations/{category}", response_model=RecommendationsOut)
def get_recommendations(
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    category: Category,
    max_price_cents: Annotated[int | None, Query(ge=0, le=1_000_000)] = None,
    free_only: bool = False,
    min_review_pct: Annotated[int | None, Query(ge=0, le=100)] = None,
    released_after: Annotated[int | None, Query(ge=1970, le=2100)] = None,
    released_before: Annotated[int | None, Query(ge=1970, le=2100)] = None,
    players: Literal["any", "multiplayer", "singleplayer"] = "any",
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> RecommendationsOut:
    """The latest list, built in the active scoring mode (``scoring_mode``: "ai" or
    "classic", from AI_GRADE; each ``run`` also carries its ``scoring_mode``,
    ``config_version`` and ``algorithm``). A list built in the other mode is never
    returned: the answer is ``status: "pending"`` while it is rebuilt. ``limit``
    returns only the first N items (``total`` still counts all of them)."""
    mode = active_mode(settings)
    run = repo.latest_recommendation_run(db, user.id, category)
    if run is None or run.scoring_mode != mode.value:
        # No list yet, or the latest one was built in the other AI_GRADE mode: never
        # show its scores (an AI prediction in classic mode, or the reverse). Rebuild.
        _queue_refresh(str(user.id), discover=run is None, cooldown=REFRESH_COOLDOWN_S)
        return RecommendationsOut(
            category=category, status="pending", scoring_mode=mode.value, run=None, items=[]
        )
    if run.config_version != config_version(settings.engine_params, mode):
        # Same mode, but the scoring parameters changed since: serve it, rebuild soon.
        _queue_refresh(str(user.id), discover=False, cooldown=REFRESH_COOLDOWN_S)
    country = settings.steam_store_country
    rows = repo.recommendation_items_view(db, run.id, user.id, country)
    taxonomy = repo.load_taxonomy(db)
    vectors = repo.load_game_vectors(db, [r["game_id"] for r in rows])
    multi_ids = {taxonomy.by_slug["multiplayer"].id} if "multiplayer" in taxonomy.by_slug else set()
    for mid in list(multi_ids):
        multi_ids |= taxonomy.descendants(mid)
    single_id = taxonomy.by_slug["singleplayer"].id if "singleplayer" in taxonomy.by_slug else None

    def keep(r: dict[str, Any]) -> bool:
        free = bool(r["price_is_free"] or r["is_free"])
        if free_only and not free:
            return False
        price = r["final_price_cents"]
        if max_price_cents is not None and not free and (price is None or price > max_price_cents):
            return False
        if min_review_pct is not None and (r["percent_positive"] or -1) < min_review_pct:
            return False
        year = r["release_date"].year if r["release_date"] else None
        if released_after is not None and (year is None or year < released_after):
            return False
        if released_before is not None and (year is None or year > released_before):
            return False
        feats = vectors.get(r["game_id"])
        fids = set(feats.features) if feats else set()
        if players == "multiplayer" and not (fids & multi_ids):
            return False
        return not (players == "singleplayer" and single_id not in fids)

    # Feedback given since the run was built applies at once: rejected games vanish.
    hidden = behaviour_repo.hidden_game_ids(db, user.id)
    visible = [r for r in rows if r["game_id"] not in hidden]
    kept_all = [r for r in visible if keep(r)]
    kept = kept_all[:limit] if limit else kept_all
    tags = _top_feature_names(db, [r["game_id"] for r in kept])
    ids = [r["game_id"] for r in kept]
    reactions = behaviour_repo.reactions(db, user.id, ids)
    ratings = {
        f.game_id: f
        for f in db.query(UserFeedback)
        .filter(UserFeedback.user_id == user.id, UserFeedback.game_id.in_(ids))
        .all()
    }
    out = RecommendationsOut(
        category=category,
        status="ready",
        scoring_mode=mode.value,
        score_kind="calibrated_satisfaction" if run.satisfaction_model_version_id else "match",
        run=RecommendationRunOut.model_validate(run, from_attributes=True),
        items=[
            _item_out(
                r,
                tags.get(r["game_id"], []),
                country,
                GameFeedbackOut.from_state(
                    r["game_id"], reactions.get(r["game_id"]), ratings.get(r["game_id"])
                )
                if r["game_id"] in reactions or r["game_id"] in ratings
                else None,
            )
            for r in kept
        ],
        filtered_out=len(visible) - len(kept_all),
        total=len(kept_all),
        hidden_by_feedback=len(rows) - len(visible),
    )
    if category == "trending":
        first_day, days, tracked = repo.player_count_coverage(db)
        source = repo.player_count_source_status(db, datetime.now(UTC))
        out.trend_status = TrendStatusOut(
            days_collected=days,
            days_needed=rec_service.trend_window_days(settings.engine_params),
            first_day=first_day,
            games_tracked=tracked,
            source=source["source"],
            last_success_at=source["last_success_at"],
            freshness_hours=source["freshness_hours"],
            reliability_7d=source["reliability_7d"],
            max_staleness_hours=settings.engine_params.trend_max_staleness_hours,
        )
        if run.data_state != "ok":
            # "Popular right now" is an absolute count personalised by Match only:
            # the classic engine (no models) in both modes.
            ctx = rec_service.load_context(
                db,
                user.id,
                settings.engine_params,
                datetime.now(UTC),
                engine=engine_for(ScoringMode.CLASSIC),
            )
            popular = rec_service.popular_now(db, ctx)
            meta = db.execute(
                text(
                    """
                    SELECT g.id, g.name, g.capsule_image_url,
                           (SELECT e.external_id FROM external_game_ids e
                             WHERE e.game_id = g.id AND e.provider = 'steam' LIMIT 1)
                      FROM games g WHERE g.id = ANY(:ids)
                    """
                ),
                {"ids": [p["game_id"] for p in popular]},
            ).all()
            info = {int(m[0]): m for m in meta}
            out.popular_now = [
                PopularNowOut(
                    game_id=p["game_id"],
                    name=info[p["game_id"]][1],
                    steam_appid=info[p["game_id"]][3],
                    capsule_image_url=info[p["game_id"]][2],
                    players=p["players"],
                    sampled_at=p["sampled_at"],
                    satisfaction_score=p["satisfaction_score"],
                    confidence_label=confidence_label(p["confidence"]),
                    reasons=[ReasonOut(**r) for r in p["reasons"]],
                )
                for p in popular
                if p["game_id"] in info
            ]
    return out


@router.post("/recommendations/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(user: CurrentUser) -> dict[str, bool]:
    """Rebuild profile and recommendations now (at most once a minute)."""
    return {"queued": _queue_refresh(str(user.id), discover=True, cooldown=REFRESH_COOLDOWN_S)}
