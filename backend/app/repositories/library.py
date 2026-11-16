"""Library, playtime-snapshot and sync-run data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AchievementSummary,
    GameReviewSummary,
    LibrarySyncRun,
    UserLibraryEntry,
)
from app.models.activity import SYNC_ACTIVE_STATUSES


def enqueue_sync_run(
    session: Session, user_id: uuid.UUID, platform: str, trigger: str
) -> tuple[LibrarySyncRun, bool]:
    """Create a queued run unless one is already queued/running (returns it, False)."""
    active = active_sync_run(session, user_id, platform)
    if active is not None:
        return active, False
    run = LibrarySyncRun(user_id=user_id, platform=platform, trigger=trigger, status="queued")
    session.add(run)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        # Concurrent request created one first (partial unique index).
        existing = active_sync_run(session, user_id, platform)
        if existing is None:
            raise
        return existing, False
    return run, True


def active_sync_run(session: Session, user_id: uuid.UUID, platform: str) -> LibrarySyncRun | None:
    return session.execute(
        select(LibrarySyncRun).where(
            LibrarySyncRun.user_id == user_id,
            LibrarySyncRun.platform == platform,
            LibrarySyncRun.status.in_(SYNC_ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()


def latest_sync_run(session: Session, user_id: uuid.UUID, platform: str) -> LibrarySyncRun | None:
    return session.execute(
        select(LibrarySyncRun)
        .where(LibrarySyncRun.user_id == user_id, LibrarySyncRun.platform == platform)
        .order_by(LibrarySyncRun.queued_at.desc(), LibrarySyncRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def library_entries(
    session: Session, user_id: uuid.UUID, platform: str
) -> dict[int, UserLibraryEntry]:
    rows = session.execute(
        select(UserLibraryEntry).where(
            UserLibraryEntry.user_id == user_id, UserLibraryEntry.platform == platform
        )
    ).scalars()
    return {e.game_id: e for e in rows}


def upsert_achievement_summary(
    session: Session, entry_id: int, status: str, achieved: int | None, total: int | None
) -> None:
    stmt = pg_insert(AchievementSummary).values(
        library_entry_id=entry_id,
        status=status,
        achieved=achieved,
        total=total,
        fetched_at=datetime.now(UTC),
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[AchievementSummary.library_entry_id],
            set_={k: stmt.excluded[k] for k in ("status", "achieved", "total", "fetched_at")},
        )
    )


def library_view(session: Session, user_id: uuid.UUID, platform: str) -> list[dict[str, Any]]:
    """Owned games (not removed) plus games rated but not owned, with catalogue data."""
    rows = session.execute(
        text(
            """
            WITH items AS (
                SELECT game_id FROM user_library
                 WHERE user_id = :user_id AND platform = :platform AND removed_at IS NULL
                UNION
                SELECT game_id FROM user_feedback WHERE user_id = :user_id
            )
            SELECT g.id AS game_id, g.name, g.header_image_url, g.capsule_image_url,
                   g.game_type, g.release_date,
                   (SELECT e.external_id FROM external_game_ids e
                     WHERE e.game_id = g.id AND e.provider = 'steam' LIMIT 1) AS steam_appid,
                   l.id IS NOT NULL AS owned, l.source AS ownership_source,
                   l.playtime_forever_minutes, l.playtime_2weeks_minutes, l.last_played_at,
                   f.rating,
                   a.achieved, a.total AS achievements_total,
                   r.label AS review_label, r.percent_positive AS review_percent_positive,
                   (SELECT COALESCE(array_agg(ft.name ORDER BY v.score DESC), '{}')
                      FROM (SELECT feature_id, MAX(value * confidence) AS score
                              FROM game_feature_values WHERE game_id = g.id
                             GROUP BY feature_id
                             ORDER BY MAX(value * confidence) DESC LIMIT 6) v
                      JOIN game_features ft ON ft.id = v.feature_id) AS top_features
            FROM items i
            JOIN games g ON g.id = i.game_id
            LEFT JOIN user_library l ON l.game_id = g.id AND l.user_id = :user_id
                 AND l.platform = :platform AND l.removed_at IS NULL
            LEFT JOIN user_feedback f ON f.game_id = g.id AND f.user_id = :user_id
            LEFT JOIN achievement_summaries a ON a.library_entry_id = l.id AND a.status = 'ok'
            LEFT JOIN game_review_summaries r ON r.game_id = g.id AND r.source = 'steam_store'
            ORDER BY l.playtime_forever_minutes DESC NULLS LAST, f.rating DESC NULLS LAST, g.name
            """
        ),
        {"user_id": user_id, "platform": platform},
    ).mappings()
    return [dict(r) for r in rows]


def library_stats(session: Session, user_id: uuid.UUID, platform: str) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                """
            SELECT
              (SELECT count(*) FROM user_library WHERE user_id = :u AND platform = :p
                 AND removed_at IS NULL) AS games_owned,
              (SELECT count(*) FROM (
                 SELECT game_id FROM user_library WHERE user_id = :u AND platform = :p
                    AND removed_at IS NULL AND playtime_forever_minutes > 0
                 UNION SELECT game_id FROM user_feedback WHERE user_id = :u) played
              ) AS games_played,
              (SELECT count(*) FROM user_feedback WHERE user_id = :u) AS games_rated,
              (SELECT COALESCE(sum(playtime_forever_minutes), 0) FROM user_library
                WHERE user_id = :u AND platform = :p AND removed_at IS NULL) AS total_minutes,
              (SELECT COALESCE(sum(playtime_2weeks_minutes), 0) FROM user_library
                WHERE user_id = :u AND platform = :p AND removed_at IS NULL) AS recent_minutes
            """
            ),
            {"u": user_id, "p": platform},
        )
        .mappings()
        .one()
    )
    return {
        "games_owned": int(row["games_owned"]),
        "games_played": int(row["games_played"]),
        "games_rated": int(row["games_rated"]),
        "total_playtime_minutes": int(row["total_minutes"]),
        "recent_playtime_minutes": int(row["recent_minutes"]),
    }


def upsert_review_summary(
    session: Session,
    game_id: int,
    source: str,
    count: int | None,
    pct: int | None,
    label: str | None,
) -> None:
    stmt = pg_insert(GameReviewSummary).values(
        game_id=game_id,
        source=source,
        review_count=count,
        percent_positive=pct,
        label=label,
        fetched_at=datetime.now(UTC),
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[GameReviewSummary.game_id, GameReviewSummary.source],
            set_={
                k: stmt.excluded[k]
                for k in ("review_count", "percent_positive", "label", "fetched_at")
            },
        )
    )


def users_due_for_scheduled_sync(
    session: Session, platform: str, *, interval: timedelta, active_within: timedelta, limit: int
) -> list[uuid.UUID]:
    now = datetime.now(UTC)
    rows = session.execute(
        text(
            """
            SELECT u.id FROM users u
            JOIN connected_platforms p ON p.user_id = u.id AND p.platform = :platform
            JOIN user_privacy_settings s ON s.user_id = u.id
            WHERE u.status = 'active'
              AND s.allow_scheduled_sync
              AND p.game_details_status IN ('accessible', 'empty')
              AND u.last_login_at > :active_since
              AND (p.last_synced_at IS NULL OR p.last_synced_at < :due_before)
              AND NOT EXISTS (SELECT 1 FROM library_sync_runs r WHERE r.user_id = u.id
                               AND r.platform = :platform AND r.status IN ('queued', 'running'))
            ORDER BY p.last_synced_at NULLS FIRST
            LIMIT :limit
            """
        ),
        {
            "platform": platform,
            "active_since": now - active_within,
            "due_before": now - interval,
            "limit": limit,
        },
    ).scalars()
    return list(rows)
