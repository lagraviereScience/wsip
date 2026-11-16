"""Behavioural events, game reactions and satisfaction prompts (data access)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.behaviour import BehaviourEvent, SatisfactionPrompt, UserGameReaction
from app.models.recommendation import RecommendationRun


def insert_events(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Append events; rows whose (user, idempotency key) already exists are skipped.

    Returns the number of rows actually inserted.
    """
    if not rows:
        return 0
    stmt = (
        pg_insert(BehaviourEvent)
        .values(list(rows))
        .on_conflict_do_nothing(
            index_elements=["user_id", "idempotency_key"],
            index_where=text("idempotency_key IS NOT NULL"),
        )
        .returning(BehaviourEvent.id)
    )
    return len(session.execute(stmt).all())


def user_runs(
    session: Session, user_id: uuid.UUID, run_ids: Iterable[int]
) -> dict[int, RecommendationRun]:
    """Recommendation runs among ``run_ids`` that belong to this user (isolation)."""
    ids = list(set(run_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(RecommendationRun).where(
            RecommendationRun.id.in_(ids), RecommendationRun.user_id == user_id
        )
    ).scalars()
    return {r.id: r for r in rows}


def run_game_ranks(session: Session, run_ids: Iterable[int]) -> dict[tuple[int, int], int]:
    ids = list(set(run_ids))
    if not ids:
        return {}
    rows = session.execute(
        text("SELECT run_id, game_id, rank FROM recommendation_items WHERE run_id = ANY(:ids)"),
        {"ids": ids},
    ).all()
    return {(int(r[0]), int(r[1])): int(r[2]) for r in rows}


def existing_game_ids(session: Session, game_ids: Iterable[int]) -> set[int]:
    ids = list(set(game_ids))
    if not ids:
        return set()
    rows = session.execute(text("SELECT id FROM games WHERE id = ANY(:ids)"), {"ids": ids})
    return {int(r[0]) for r in rows}


def events_for_user(
    session: Session,
    user_id: uuid.UUID,
    *,
    limit: int = 100,
    before_id: int | None = None,
    types: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT e.id, e.event_type, e.occurred_at, e.game_id, g.name AS game_name,
                   f.slug AS feature, e.category, e.position, e.model_version, e.surface,
                   e.metadata
              FROM behaviour_events e
              LEFT JOIN games g ON g.id = e.game_id
              LEFT JOIN game_features f ON f.id = e.feature_id
             WHERE e.user_id = :u
               AND (CAST(:before AS bigint) IS NULL OR e.id < :before)
               AND (CAST(:types AS text[]) IS NULL OR e.event_type = ANY(:types))
             ORDER BY e.id DESC
             LIMIT :n
            """
        ),
        {"u": user_id, "before": before_id, "types": list(types) if types else None, "n": limit},
    ).mappings()
    return [dict(r) for r in rows]


def last_exposures(
    session: Session, user_id: uuid.UUID, game_ids: Iterable[int], since: datetime
) -> dict[int, dict[str, Any]]:
    """Most recent recommendation exposure per game (for attributing later outcomes)."""
    ids = list(set(game_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (game_id)
                   game_id, recommendation_run_id, category, position, model_version,
                   occurred_at
              FROM behaviour_events
             WHERE user_id = :u AND game_id = ANY(:ids)
               AND recommendation_run_id IS NOT NULL AND occurred_at >= :since
             ORDER BY game_id, occurred_at DESC, id DESC
            """
        ),
        {"u": user_id, "ids": ids, "since": since},
    ).mappings()
    return {int(r["game_id"]): dict(r) for r in rows}


# --- Reactions -------------------------------------------------------------------


def reaction(session: Session, user_id: uuid.UUID, game_id: int) -> UserGameReaction | None:
    return session.get(UserGameReaction, (user_id, game_id))


def reactions(
    session: Session, user_id: uuid.UUID, game_ids: Iterable[int] | None = None
) -> dict[int, UserGameReaction]:
    stmt = select(UserGameReaction).where(UserGameReaction.user_id == user_id)
    if game_ids is not None:
        stmt = stmt.where(UserGameReaction.game_id.in_(list(set(game_ids))))
    return {r.game_id: r for r in session.execute(stmt).scalars()}


def reaction_kinds(r: UserGameReaction) -> list[str]:
    """The reaction row as a list of active feedback kinds."""
    kinds: list[str] = []
    if r.reaction:
        kinds.append(r.reaction)
    if r.favourite:
        kinds.append("favourite")
    if r.saved:
        kinds.append("save_for_later")
    if r.dismissal:
        kinds.append(r.dismissal)
    if r.already_played:
        kinds.append("already_played")
    return kinds


def hidden_game_ids(session: Session, user_id: uuid.UUID) -> set[int]:
    """Games never to recommend again: dismissed, disliked, already played, or rated
    Disliked/Hated (explicit negatives are hard constraints, prompt 4)."""
    rows = session.execute(
        text(
            """
            SELECT game_id FROM user_game_reactions
             WHERE user_id = :u
               AND (dismissal IS NOT NULL OR reaction = 'dislike' OR already_played)
            UNION
            SELECT game_id FROM user_feedback WHERE user_id = :u AND rating < 0
            """
        ),
        {"u": user_id},
    )
    return {int(r[0]) for r in rows}


def feedback_overview(session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every game with current feedback (reaction or rating), newest first."""
    rows = session.execute(
        text(
            """
            SELECT g.id AS game_id, g.name, g.capsule_image_url,
                   (SELECT e.external_id FROM external_game_ids e
                     WHERE e.game_id = g.id AND e.provider = 'steam' LIMIT 1) AS steam_appid,
                   r.reaction, COALESCE(r.favourite, false) AS favourite,
                   COALESCE(r.saved, false) AS saved, r.dismissal, r.dismissal_reason,
                   COALESCE(r.already_played, false) AS already_played,
                   f.rating, f.source AS rating_source,
                   l.id IS NOT NULL AS owned,
                   GREATEST(r.updated_at, f.updated_at) AS updated_at
              FROM (SELECT * FROM user_game_reactions WHERE user_id = :u) r
              FULL OUTER JOIN (SELECT * FROM user_feedback
                                WHERE user_id = :u AND source <> 'library_entry') f
                ON f.game_id = r.game_id
              JOIN games g ON g.id = COALESCE(r.game_id, f.game_id)
              LEFT JOIN user_library l ON l.game_id = g.id AND l.user_id = :u
                   AND l.removed_at IS NULL
             ORDER BY updated_at DESC, g.id
            """
        ),
        {"u": user_id},
    ).mappings()
    return [dict(r) for r in rows]


# --- Satisfaction prompts ----------------------------------------------------------


def prompt(session: Session, user_id: uuid.UUID, game_id: int) -> SatisfactionPrompt:
    row = session.get(SatisfactionPrompt, (user_id, game_id))
    if row is None:
        row = SatisfactionPrompt(user_id=user_id, game_id=game_id, times_shown=0, declined=False)
        session.add(row)
        session.flush()
    return row


def last_prompt_shown_at(session: Session, user_id: uuid.UUID) -> datetime | None:
    value = session.execute(
        text("SELECT max(last_shown_at) FROM satisfaction_prompts WHERE user_id = :u"),
        {"u": user_id},
    ).scalar_one_or_none()
    return value


def satisfaction_candidates(
    session: Session,
    user_id: uuid.UUID,
    now: datetime,
    *,
    min_minutes_after_exposure: int,
    exposure_window: timedelta,
    max_times_shown: int,
) -> list[dict[str, Any]]:
    """Recommended games the user has since played enough to judge, not yet rated.

    "Played since the recommendation" comes from ``playtime_change`` events after the
    first exposure of that game in a recommendation list, so a game the user had
    already sunk hours into before we recommended it never qualifies.
    """
    rows = session.execute(
        text(
            """
            WITH exposed AS (
                SELECT game_id, min(occurred_at) AS first_exposed_at
                  FROM behaviour_events
                 WHERE user_id = :u AND recommendation_run_id IS NOT NULL
                   AND game_id IS NOT NULL AND occurred_at >= :since
                 GROUP BY game_id
            ),
            played AS (
                SELECT e.game_id, sum((e.metadata->>'delta_minutes')::int) AS minutes_since
                  FROM behaviour_events e JOIN exposed x ON x.game_id = e.game_id
                 WHERE e.user_id = :u AND e.event_type = 'playtime_change'
                   AND e.occurred_at > x.first_exposed_at
                 GROUP BY e.game_id
            )
            SELECT x.game_id, x.first_exposed_at, p.minutes_since, g.name,
                   g.capsule_image_url, l.playtime_forever_minutes
              FROM exposed x
              JOIN played p ON p.game_id = x.game_id
              JOIN games g ON g.id = x.game_id
              JOIN user_library l ON l.game_id = x.game_id AND l.user_id = :u
                   AND l.removed_at IS NULL
              LEFT JOIN user_feedback f ON f.game_id = x.game_id AND f.user_id = :u
              LEFT JOIN satisfaction_prompts s ON s.game_id = x.game_id AND s.user_id = :u
             WHERE p.minutes_since >= :min_minutes
               AND f.id IS NULL
               AND (s.user_id IS NULL OR (
                        NOT s.declined AND s.answered_at IS NULL
                        AND s.times_shown < :max_shown
                        AND (s.snoozed_until IS NULL OR s.snoozed_until <= :now)))
             ORDER BY x.first_exposed_at, x.game_id
            """
        ),
        {
            "u": user_id,
            "since": now - exposure_window,
            "now": now,
            "min_minutes": min_minutes_after_exposure,
            "max_shown": max_times_shown,
        },
    ).mappings()
    return [dict(r) for r in rows]
