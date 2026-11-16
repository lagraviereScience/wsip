"""Behavioural events, game feedback, post-play satisfaction and the game page.

Every endpoint acts on the signed-in user's own data only. Exposure context sent
by the browser is checked against the user's own recommendation runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from sqlalchemy import text

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.api.routes.recommendations import PREFERENCE_DEBOUNCE_S, _queue_refresh
from app.core.rate_limit import FixedWindowLimiter
from app.database.redis import get_redis
from app.models.activity import UserFeedback
from app.recommendations.ranking import explain
from app.recommendations.ranking.compatibility import compatibility
from app.repositories import behaviour as behaviour_repo
from app.repositories import recommendation as rec_repo
from app.schemas.feedback import (
    EventHistoryOut,
    EventOut,
    EventsIn,
    EventsOut,
    FeedbackGameOut,
    FeedbackKind,
    FeedbackListOut,
    GameFeedbackOut,
    GamePageOut,
    PromptActionIn,
    PromptOut,
    PromptStatusOut,
    ReactionIn,
    SatisfactionIn,
)
from app.schemas.recommendation import confidence_label
from app.services import feedback as feedback_service
from app.services.profile import effective_preferences

router = APIRouter(prefix="/me", tags=["feedback"])

EVENT_REQUESTS_PER_MINUTE = 60
FEEDBACK_REQUESTS_PER_MINUTE = 120
GameId = Annotated[int, Path(ge=1, le=2**62)]


def _limit(namespace: str, per_minute: int, user_id: str) -> None:
    if not FixedWindowLimiter(get_redis(), namespace, per_minute).hit(user_id).allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; slow down.")


def _refresh_soon(user_id: str) -> None:
    """Profile + lists rebuild a few seconds after feedback (debounced)."""
    _queue_refresh(
        user_id, discover=False, cooldown=PREFERENCE_DEBOUNCE_S, countdown=PREFERENCE_DEBOUNCE_S
    )


def _current(db: DbSession, user_id: Any, game_id: int) -> GameFeedbackOut:
    rating = db.query(UserFeedback).filter_by(user_id=user_id, game_id=game_id).one_or_none()
    return GameFeedbackOut.from_state(
        game_id, behaviour_repo.reaction(db, user_id, game_id), rating
    )


# --- Events -------------------------------------------------------------------------


@router.post("/events", response_model=EventsOut, status_code=status.HTTP_202_ACCEPTED)
def post_events(db: DbSession, user: CurrentUser, body: EventsIn) -> EventsOut:
    """Impressions (actually visible cards), clicks, game page views, store visits."""
    _limit("events", EVENT_REQUESTS_PER_MINUTE, str(user.id))
    result = feedback_service.record_client_events(
        db,
        user.id,
        [
            feedback_service.ClientEvent(
                event_type=e.type,
                game_id=e.game_id,
                idempotency_key=e.idempotency_key,
                occurred_at=e.occurred_at,
                recommendation_run_id=e.recommendation_run_id,
                position=e.position,
                surface=e.surface,
                context=dict(e.context) if e.context else None,
            )
            for e in body.events
        ],
        datetime.now(UTC),
    )
    db.commit()
    return EventsOut(
        accepted=result.accepted, duplicates=result.duplicates, rejected=result.rejected
    )


@router.get("/events", response_model=EventHistoryOut)
def get_events(
    db: DbSession,
    user: CurrentUser,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    feedback_only: bool = False,
) -> EventHistoryOut:
    """The user's own event history, newest first."""
    types = (
        [
            "like",
            "dislike",
            "favourite",
            "save_for_later",
            "not_interested",
            "not_my_type",
            "already_played",
            "satisfaction",
            "feature_preference",
        ]
        if feedback_only
        else None
    )
    rows = behaviour_repo.events_for_user(
        db, user.id, limit=limit + 1, before_id=before, types=types
    )
    page = rows[:limit]
    return EventHistoryOut(
        events=[EventOut(**r) for r in page],
        next_before=page[-1]["id"] if len(rows) > limit and page else None,
    )


# --- Feedback ---------------------------------------------------------------------------


@router.put("/games/{game_id}/feedback/{kind}", response_model=GameFeedbackOut)
def set_feedback(
    db: DbSession, user: CurrentUser, game_id: GameId, kind: FeedbackKind, body: ReactionIn
) -> GameFeedbackOut:
    """Turn one kind of feedback on (``on: true``) or undo it (``on: false``)."""
    _limit("feedback", FEEDBACK_REQUESTS_PER_MINUTE, str(user.id))
    if body.reason is not None and kind != "not_interested":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "reason is only for not_interested"
        )
    try:
        feedback_service.set_reaction(
            db,
            user.id,
            game_id,
            kind,
            on=body.on,
            reason=body.reason,
            now=datetime.now(UTC),
            exposure=feedback_service.Exposure(
                body.recommendation_run_id, body.position, body.surface
            ),
        )
    except feedback_service.UnknownGame as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown game") from exc
    db.commit()
    _refresh_soon(str(user.id))
    return _current(db, user.id, game_id)


@router.put("/games/{game_id}/satisfaction", response_model=GameFeedbackOut)
def set_satisfaction(
    db: DbSession, user: CurrentUser, game_id: GameId, body: SatisfactionIn
) -> GameFeedbackOut:
    """ "Did you enjoy this game?" Loved (2) ... Hated (-2); null clears the answer."""
    _limit("feedback", FEEDBACK_REQUESTS_PER_MINUTE, str(user.id))
    try:
        feedback_service.set_satisfaction(
            db,
            user.id,
            game_id,
            body.rating,
            source=body.source,
            now=datetime.now(UTC),
            exposure=feedback_service.Exposure(
                body.recommendation_run_id, body.position, body.surface
            ),
        )
    except feedback_service.UnknownGame as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown game") from exc
    db.commit()
    _refresh_soon(str(user.id))
    return _current(db, user.id, game_id)


@router.get("/feedback", response_model=FeedbackListOut)
def list_feedback(db: DbSession, user: CurrentUser) -> FeedbackListOut:
    """Every game the user reacted to or rated from a recommendation, to review or undo."""
    return FeedbackListOut(
        games=[FeedbackGameOut(**r) for r in behaviour_repo.feedback_overview(db, user.id)]
    )


# --- Post-play satisfaction question ---------------------------------------------------------


@router.get("/satisfaction-prompt", response_model=PromptStatusOut)
def get_prompt(db: DbSession, user: CurrentUser) -> PromptStatusOut:
    p = feedback_service.next_prompt(db, user.id, datetime.now(UTC))
    if p is None:
        return PromptStatusOut(prompt=None)
    return PromptStatusOut(
        prompt=PromptOut(
            game_id=p["game_id"],
            name=p["name"],
            capsule_image_url=p["capsule_image_url"],
            minutes_since_recommended=int(p["minutes_since"]),
            question=f"Did you enjoy {p['name']}?",
        )
    )


@router.post("/satisfaction-prompt/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
def prompt_action(
    db: DbSession, user: CurrentUser, game_id: GameId, body: PromptActionIn
) -> Response:
    """Record that the question was shown, snoozed ("Not now") or declined."""
    try:
        feedback_service.prompt_action(db, user.id, game_id, body.action, datetime.now(UTC))
    except feedback_service.UnknownGame as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown game") from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Game page ------------------------------------------------------------------------------


@router.get("/games/{game_id}", response_model=GamePageOut)
def game_page(
    db: DbSession, user: CurrentUser, settings: AppSettings, game_id: GameId
) -> GamePageOut:
    row = (
        db.execute(
            text(
                """
                SELECT g.id, g.name, g.header_image_url, g.short_description, g.release_date,
                       (SELECT e.external_id FROM external_game_ids e
                         WHERE e.game_id = g.id AND e.provider = 'steam' LIMIT 1) AS steam_appid,
                       l.id IS NOT NULL AS owned, l.playtime_forever_minutes,
                       r.review_count, r.percent_positive, r.label AS review_label,
                       p.is_free, p.formatted_final_price, p.formatted_original_price,
                       p.discount_pct
                  FROM games g
                  LEFT JOIN user_library l ON l.game_id = g.id AND l.user_id = :u
                       AND l.removed_at IS NULL
                  LEFT JOIN game_review_summaries r ON r.game_id = g.id
                       AND r.source = 'steam_store'
                  LEFT JOIN game_prices p ON p.game_id = g.id AND p.country_code = :c
                 WHERE g.id = :g
                """
            ),
            {"u": user.id, "g": game_id, "c": settings.steam_store_country},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown game")
    taxonomy = rec_repo.load_taxonomy(db)
    vec = rec_repo.load_game_vectors(db, [game_id]).get(game_id)
    match = label = None
    reasons: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    tags: list[str] = []
    if vec is not None and not vec.is_empty:
        eff = effective_preferences(db, user.id)
        compat = compatibility(vec, eff.preferences, taxonomy, settings.engine_params)
        match, label = compat.score, confidence_label(compat.confidence)
        reasons = [r.to_dict() for r in explain.feature_reasons(compat, taxonomy, eff.recent)]
        contributions = [
            {
                "feature": taxonomy.nodes[c.feature_id].slug,
                "name": taxonomy.nodes[c.feature_id].name,
                "group": c.group,
                "points": round(c.points, 3),
                "origin": c.origin,
            }
            for c in compat.contributions
        ]
        ranked = sorted(
            vec.features.items(), key=lambda kv: (-(kv[1].value * kv[1].confidence), kv[0])
        )
        tags = [taxonomy.nodes[fid].name for fid, _ in ranked[:8] if fid in taxonomy.nodes]
    latest = db.execute(
        text(
            """
            SELECT r.id, r.category, i.rank FROM recommendation_items i
              JOIN recommendation_runs r ON r.id = i.run_id
             WHERE r.user_id = :u AND i.game_id = :g
             ORDER BY r.created_at DESC, r.id DESC LIMIT 1
            """
        ),
        {"u": user.id, "g": game_id},
    ).one_or_none()
    review = (
        {
            "count": row["review_count"],
            "percent_positive": row["percent_positive"],
            "label": row["review_label"],
        }
        if row["review_label"] or row["review_count"] is not None
        else None
    )
    price = (
        {
            "is_free": bool(row["is_free"]),
            "formatted_final": row["formatted_final_price"],
            "formatted_original": row["formatted_original_price"],
            "discount_pct": row["discount_pct"],
        }
        if row["is_free"] is not None
        else None
    )
    sources, completion = _attribution(db, game_id, settings.steam_store_country)
    return GamePageOut(
        game_id=game_id,
        name=row["name"],
        steam_appid=row["steam_appid"],
        header_image_url=row["header_image_url"],
        short_description=row["short_description"],
        release_date=row["release_date"],
        tags=tags,
        owned=bool(row["owned"]),
        playtime_minutes=row["playtime_forever_minutes"],
        feedback=_current(db, user.id, game_id),
        match=match,
        confidence_label=label,
        reasons=reasons,
        contributions=contributions,
        recommendation_run_id=latest[0] if latest else None,
        category=latest[1] if latest else None,
        rank=latest[2] if latest else None,
        review=review,
        price=price,
        completion=completion,
        sources=sources,
    )


def _hours(seconds: int | None) -> float | None:
    return round(seconds / 3600, 1) if seconds else None


def _attribution(
    db: DbSession, game_id: int, country: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Source and fetch time for each kind of game data, and completion times."""
    row = db.execute(
        text(
            """
            SELECT (SELECT fetched_at FROM game_sources
                     WHERE game_id = :g AND provider = 'steam_store') AS metadata_at,
                   (SELECT fetched_at FROM game_review_summaries
                     WHERE game_id = :g AND source = 'steam_store') AS reviews_at,
                   (SELECT fetched_at FROM game_prices
                     WHERE game_id = :g AND country_code = :c) AS price_at
            """
        ),
        {"g": game_id, "c": country},
    ).one()
    sources = [
        {
            "data": "Description, artwork, genres and tags",
            "source": "Steam Store",
            "fetched_at": row[0],
        },
        {"data": "Reviews", "source": "Steam Store", "fetched_at": row[1]},
        {"data": f"Price and discount ({country})", "source": "Steam Store", "fetched_at": row[2]},
    ]
    ct = db.execute(
        text(
            """
            SELECT hastily_seconds, normally_seconds, completely_seconds, submissions, fetched_at
              FROM game_completion_times WHERE game_id = :g AND source = 'igdb'
            """
        ),
        {"g": game_id},
    ).one_or_none()
    completion = None
    if ct is not None and any(v is not None for v in ct[:3]):
        completion = {
            "source": "IGDB",
            "hastily_hours": _hours(ct[0]),
            "normally_hours": _hours(ct[1]),
            "completely_hours": _hours(ct[2]),
            "submissions": ct[3],
            "fetched_at": ct[4],
        }
        sources.append({"data": "Completion times", "source": "IGDB", "fetched_at": ct[4]})
    return [s for s in sources if s["fetched_at"] is not None], completion
