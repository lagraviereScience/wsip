"""Persistence for profiles, manual preferences, recommendations, prices and trends."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.catalogue import FeatureCategory, GameFeature, GameFeatureValue
from app.models.recommendation import (
    GameDiscoverySource,
    GamePrice,
    PlayerCountSample,
    ProfileRun,
    RecommendationItem,
    RecommendationRun,
    UserFeaturePreference,
    UserFeaturePreferenceHistory,
    UserPreference,
    UserPreferenceEvent,
)
from app.recommendations.features.vectors import FeatureNode, GameVector, Taxonomy, merge_sources
from app.recommendations.profiling.preferences import InferredPreference, PlayRecord

HISTORY_EPSILON = 0.01  # smaller changes are not worth a history row


# --- Taxonomy and vectors -----------------------------------------------------


def load_taxonomy(session: Session) -> Taxonomy:
    rows = session.execute(
        select(
            GameFeature.id,
            GameFeature.slug,
            GameFeature.name,
            FeatureCategory.slug,
            FeatureCategory.scoring_group,
            GameFeature.parent_id,
        )
        .join(FeatureCategory, FeatureCategory.id == GameFeature.category_id)
        .where(GameFeature.status == "active")
    ).all()
    return Taxonomy(FeatureNode(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows)


def load_game_vectors(
    session: Session, game_ids: Iterable[int] | None = None
) -> dict[int, GameVector]:
    """Merged feature vectors. ``game_ids=None`` loads every catalogue game (type game)."""
    stmt = select(
        GameFeatureValue.game_id,
        GameFeatureValue.feature_id,
        GameFeatureValue.value,
        GameFeatureValue.confidence,
    )
    if game_ids is None:
        stmt = stmt.where(
            text(
                "game_feature_values.game_id IN (SELECT id FROM games "
                "WHERE game_type = 'game' AND merged_into_game_id IS NULL)"
            )
        )
    else:
        ids = list(set(game_ids))
        if not ids:
            return {}
        stmt = stmt.where(GameFeatureValue.game_id.in_(ids))
    rows_by_game: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for gid, fid, value, conf in session.execute(stmt):
        rows_by_game[gid].append((fid, value, conf))
    return {gid: GameVector(gid, merge_sources(rows)) for gid, rows in rows_by_game.items()}


# --- Library input ------------------------------------------------------------


def play_records(
    session: Session, user_id: uuid.UUID, platform: str, now: datetime
) -> list[PlayRecord]:
    """Owned games (not removed) plus rated games, as profile inputs."""
    rows = session.execute(
        text(
            """
            SELECT COALESCE(l.game_id, f.game_id) AS game_id,
                   l.id IS NOT NULL AS owned,
                   l.playtime_forever_minutes, l.playtime_2weeks_minutes, l.last_played_at,
                   f.rating
              FROM (SELECT * FROM user_library
                     WHERE user_id = :u AND platform = :p AND removed_at IS NULL) l
              FULL OUTER JOIN (SELECT * FROM user_feedback WHERE user_id = :u) f
                ON f.game_id = l.game_id
             ORDER BY 1
            """
        ),
        {"u": user_id, "p": platform},
    ).mappings()
    out: list[PlayRecord] = []
    for r in rows:
        last = r["last_played_at"]
        out.append(
            PlayRecord(
                game_id=int(r["game_id"]),
                owned=bool(r["owned"]),
                lifetime_minutes=r["playtime_forever_minutes"],
                recent_minutes=r["playtime_2weeks_minutes"],
                days_since_last_play=(now - last).total_seconds() / 86400 if last else None,
                rating=r["rating"],
            )
        )
    return out


# --- Manual preferences -------------------------------------------------------


def manual_preferences(session: Session, user_id: uuid.UUID) -> list[UserPreference]:
    return list(
        session.execute(select(UserPreference).where(UserPreference.user_id == user_id)).scalars()
    )


def set_manual_preference(
    session: Session,
    user_id: uuid.UUID,
    feature_id: int,
    value: float | None,
    excluded: bool,
) -> bool:
    """Upsert (or clear, when value is None and not excluded) and log the change.

    Returns False when nothing changed."""
    current = session.get(UserPreference, (user_id, feature_id))
    old_value = current.value if current else None
    old_excluded = current.excluded if current else False
    if (old_value, old_excluded) == (value, excluded):
        return False
    if value is None and not excluded:
        if current is not None:
            session.delete(current)
    elif current is None:
        session.add(
            UserPreference(user_id=user_id, feature_id=feature_id, value=value, excluded=excluded)
        )
    else:
        current.value = value
        current.excluded = excluded
    session.add(
        UserPreferenceEvent(
            user_id=user_id,
            feature_id=feature_id,
            old_value=old_value,
            new_value=value,
            old_excluded=old_excluded,
            new_excluded=excluded,
        )
    )
    session.flush()
    return True


def preference_events(
    session: Session, user_id: uuid.UUID, limit: int = 50
) -> list[UserPreferenceEvent]:
    return list(
        session.execute(
            select(UserPreferenceEvent)
            .where(UserPreferenceEvent.user_id == user_id)
            .order_by(UserPreferenceEvent.created_at.desc(), UserPreferenceEvent.id.desc())
            .limit(limit)
        ).scalars()
    )


# --- Profiles -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileSummaryRow:
    run: ProfileRun
    preferences: list[UserFeaturePreference]


def save_profile(
    session: Session,
    user_id: uuid.UUID,
    run: ProfileRun,
    preferences: dict[int, InferredPreference],
) -> ProfileRun:
    """Store the run, replace current inferred values and record what changed."""
    session.add(run)
    session.flush()
    previous = {
        p.feature_id: p
        for p in session.execute(
            select(UserFeaturePreference).where(UserFeaturePreference.user_id == user_id)
        ).scalars()
    }
    history: list[dict[str, Any]] = []
    for fid, pref in preferences.items():
        old = previous.get(fid)
        if (
            old is None
            or abs(old.value - pref.value) >= HISTORY_EPSILON
            or abs(old.confidence - pref.confidence) >= HISTORY_EPSILON
        ):
            history.append(
                {
                    "profile_run_id": run.id,
                    "feature_id": fid,
                    "value": pref.value,
                    "confidence": pref.confidence,
                    "historical": pref.historical,
                    "recent": pref.recent,
                    "satisfaction": pref.satisfaction,
                    "feedback": pref.feedback,
                }
            )
    for fid in previous.keys() - preferences.keys():
        history.append(
            {
                "profile_run_id": run.id,
                "feature_id": fid,
                "value": None,
                "confidence": 0.0,
                "historical": None,
                "recent": None,
                "satisfaction": None,
                "feedback": None,
            }
        )
    session.execute(delete(UserFeaturePreference).where(UserFeaturePreference.user_id == user_id))
    if preferences:
        session.execute(
            pg_insert(UserFeaturePreference),
            [
                {
                    "user_id": user_id,
                    "feature_id": fid,
                    "profile_run_id": run.id,
                    "value": p.value,
                    "confidence": p.confidence,
                    "historical": p.historical,
                    "historical_confidence": p.historical_confidence,
                    "recent": p.recent,
                    "recent_confidence": p.recent_confidence,
                    "satisfaction": p.satisfaction,
                    "satisfaction_confidence": p.satisfaction_confidence,
                    "feedback": p.feedback,
                    "feedback_confidence": p.feedback_confidence,
                    "minutes_lifetime": p.minutes_lifetime,
                    "minutes_recent": p.minutes_recent,
                    "evidence_game_ids": list(p.evidence_games),
                }
                for fid, p in preferences.items()
            ],
        )
    if history:
        session.execute(pg_insert(UserFeaturePreferenceHistory), history)
    return run


def latest_profile_run(session: Session, user_id: uuid.UUID) -> ProfileRun | None:
    return session.execute(
        select(ProfileRun)
        .where(ProfileRun.user_id == user_id, ProfileRun.status == "succeeded")
        .order_by(ProfileRun.created_at.desc(), ProfileRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def inferred_preferences(session: Session, user_id: uuid.UUID) -> list[UserFeaturePreference]:
    return list(
        session.execute(
            select(UserFeaturePreference).where(UserFeaturePreference.user_id == user_id)
        ).scalars()
    )


def preference_history(
    session: Session, user_id: uuid.UUID, feature_id: int, limit: int = 30
) -> list[tuple[datetime, UserFeaturePreferenceHistory]]:
    rows = session.execute(
        select(ProfileRun.created_at, UserFeaturePreferenceHistory)
        .join(ProfileRun, ProfileRun.id == UserFeaturePreferenceHistory.profile_run_id)
        .where(ProfileRun.user_id == user_id, UserFeaturePreferenceHistory.feature_id == feature_id)
        .order_by(ProfileRun.created_at.desc())
        .limit(limit)
    ).all()
    return [(r[0], r[1]) for r in rows]


# --- Recommendations ----------------------------------------------------------


def save_recommendation_run(
    session: Session, run: RecommendationRun, items: Sequence[dict[str, Any]]
) -> RecommendationRun:
    run.items_count = len(items)
    session.add(run)
    session.flush()
    if items:
        session.execute(
            pg_insert(RecommendationItem),
            [{**item, "run_id": run.id, "rank": i + 1} for i, item in enumerate(items)],
        )
    return run


def latest_recommendation_run(
    session: Session, user_id: uuid.UUID, category: str
) -> RecommendationRun | None:
    return session.execute(
        select(RecommendationRun)
        .where(
            RecommendationRun.user_id == user_id,
            RecommendationRun.category == category,
            RecommendationRun.status == "succeeded",
        )
        .order_by(RecommendationRun.created_at.desc(), RecommendationRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def recommendation_items_view(
    session: Session, run_id: int, user_id: uuid.UUID, country: str
) -> list[dict[str, Any]]:
    """Items joined with live catalogue, price, review and ownership data."""
    rows = session.execute(
        text(
            """
            SELECT i.rank, i.game_id, i.score, i.satisfaction_score, i.backlog_score,
                   i.trend_score, i.collaborative_score, i.predicted_satisfaction, i.confidence,
                   i.metadata_confidence,
                   i.group_scores,
                   i.contributions, i.reasons, i.candidate_sources,
                   g.name, g.header_image_url, g.capsule_image_url, g.release_date, g.is_free,
                   g.short_description,
                   (SELECT e.external_id FROM external_game_ids e
                     WHERE e.game_id = g.id AND e.provider = 'steam' LIMIT 1) AS steam_appid,
                   l.id IS NOT NULL AS owned,
                   l.playtime_forever_minutes, l.last_played_at,
                   r.review_count, r.percent_positive, r.label AS review_label,
                   p.final_price_cents, p.original_price_cents, p.discount_pct,
                   p.formatted_final_price, p.formatted_original_price,
                   p.is_free AS price_is_free, p.fetched_at AS price_fetched_at
              FROM recommendation_items i
              JOIN games g ON g.id = i.game_id
              LEFT JOIN user_library l ON l.game_id = g.id AND l.user_id = :u
                   AND l.removed_at IS NULL
              LEFT JOIN game_review_summaries r ON r.game_id = g.id AND r.source = 'steam_store'
              LEFT JOIN game_prices p ON p.game_id = g.id AND p.country_code = :c
             WHERE i.run_id = :run
             ORDER BY i.rank
            """
        ),
        {"run": run_id, "u": user_id, "c": country},
    ).mappings()
    return [dict(r) for r in rows]


# --- Catalogue support: reviews, prices, discovery -------------------------------


def review_counts(session: Session, game_ids: Iterable[int]) -> dict[int, int]:
    ids = list(set(game_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            "SELECT game_id, review_count FROM game_review_summaries "
            "WHERE source = 'steam_store' AND game_id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    return {int(g): int(c or 0) for g, c in rows}


def game_meta(session: Session, game_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Fields used by candidate filters (type, release date, free, price, reviews)."""
    ids = list(set(game_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT g.id, g.name, g.game_type, g.release_date, g.is_free,
                   r.review_count, r.percent_positive
              FROM games g
              LEFT JOIN game_review_summaries r ON r.game_id = g.id AND r.source = 'steam_store'
             WHERE g.id = ANY(:ids) AND g.merged_into_game_id IS NULL
            """
        ),
        {"ids": ids},
    ).mappings()
    return {int(r["id"]): dict(r) for r in rows}


def upsert_price(
    session: Session,
    game_id: int,
    country: str,
    *,
    is_free: bool,
    final_cents: int | None,
    original_cents: int | None,
    discount_pct: int | None,
    formatted_final: str | None,
    formatted_original: str | None,
) -> None:
    stmt = pg_insert(GamePrice).values(
        game_id=game_id,
        country_code=country,
        is_free=is_free,
        final_price_cents=final_cents,
        original_price_cents=original_cents,
        discount_pct=discount_pct,
        formatted_final_price=formatted_final,
        formatted_original_price=formatted_original,
        fetched_at=datetime.now(UTC),
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[GamePrice.game_id, GamePrice.country_code],
            set_={
                k: stmt.excluded[k]
                for k in (
                    "is_free",
                    "final_price_cents",
                    "original_price_cents",
                    "discount_pct",
                    "formatted_final_price",
                    "formatted_original_price",
                    "fetched_at",
                )
            },
        )
    )


def record_discovery(session: Session, game_ids: Iterable[int], source: str) -> None:
    now = datetime.now(UTC)
    values = [{"game_id": g, "source": source[:64], "last_seen_at": now} for g in set(game_ids)]
    if not values:
        return
    stmt = pg_insert(GameDiscoverySource)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[GameDiscoverySource.game_id, GameDiscoverySource.source],
            set_={"last_seen_at": stmt.excluded.last_seen_at},
        ),
        values,
    )


def discovery_sources(session: Session, game_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(set(game_ids))
    if not ids:
        return {}
    out: dict[int, list[str]] = defaultdict(list)
    for gid, src in session.execute(
        select(GameDiscoverySource.game_id, GameDiscoverySource.source)
        .where(GameDiscoverySource.game_id.in_(ids))
        .order_by(GameDiscoverySource.source)
    ):
        out[gid].append(src)
    return dict(out)


def steam_tag_ids_for_features(
    session: Session, feature_ids: Iterable[int]
) -> dict[int, list[int]]:
    """Active Steam tag ids mapped (confidence >= 0.8) to each canonical feature."""
    ids = list(set(feature_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT m.feature_id, t.external_id
              FROM provider_tag_mappings m
              JOIN provider_tags t ON t.provider = m.provider AND t.kind = m.tag_kind
                   AND lower(t.name) = lower(m.original_tag)
             WHERE m.provider = 'steam_store' AND m.tag_kind = 'tag' AND m.status = 'active'
               AND m.confidence >= 0.8 AND m.feature_id = ANY(:ids)
             ORDER BY m.feature_id, m.confidence DESC, t.external_id
            """
        ),
        {"ids": ids},
    )
    out: dict[int, list[int]] = defaultdict(list)
    for fid, ext in rows:
        if str(ext).isdigit():
            out[int(fid)].append(int(ext))
    return dict(out)


# --- Player counts --------------------------------------------------------------


def insert_player_counts(session: Session, sampled_at: datetime, counts: dict[int, int]) -> int:
    if not counts:
        return 0
    session.execute(
        pg_insert(PlayerCountSample).on_conflict_do_nothing(),
        [{"game_id": g, "sampled_at": sampled_at, "player_count": c} for g, c in counts.items()],
    )
    return len(counts)


def aggregate_player_counts(session: Session, day: date) -> int:
    """(Re)build the daily aggregate for one UTC day from the raw samples."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    result = session.execute(
        text(
            """
            INSERT INTO player_count_daily (game_id, day, avg_players, max_players, samples)
            SELECT game_id, CAST(:day AS date), avg(player_count), max(player_count), count(*)
              FROM player_count_samples
             WHERE sampled_at >= :start AND sampled_at < :end
             GROUP BY game_id
            ON CONFLICT (game_id, day) DO UPDATE
               SET avg_players = EXCLUDED.avg_players,
                   max_players = EXCLUDED.max_players,
                   samples = EXCLUDED.samples
            """
        ),
        {"day": day, "start": start, "end": start + timedelta(days=1)},
    )
    return int(getattr(result, "rowcount", 0) or 0)


def prune_player_samples(session: Session, older_than: datetime) -> None:
    session.execute(delete(PlayerCountSample).where(PlayerCountSample.sampled_at < older_than))


def daily_player_series(
    session: Session, first_day: date, last_day: date, min_samples_per_day: int
) -> dict[int, list[float | None]]:
    """Per game, one daily average per day from first_day to last_day (None = missing)."""
    n_days = (last_day - first_day).days + 1
    rows = session.execute(
        text(
            """
            SELECT game_id, day, avg_players FROM player_count_daily
             WHERE day BETWEEN :a AND :b AND samples >= :m
            """
        ),
        {"a": first_day, "b": last_day, "m": min_samples_per_day},
    )
    series: dict[int, list[float | None]] = {}
    for gid, day, avg in rows:
        s = series.setdefault(int(gid), [None] * n_days)
        s[(day - first_day).days] = float(avg)
    return series


def player_count_source_status(session: Session, now: datetime, days: int = 7) -> dict[str, Any]:
    """Freshness and reliability of the player-count source over the last ``days``.

    - freshness: hours since the last pass that stored at least one count;
    - reliability: share of attempted calls that succeeded (no data counts as an
      answer, failures don't), over passes in the window.
    """
    last_ok = session.execute(
        text("SELECT max(started_at) FROM player_count_passes WHERE sampled > 0")
    ).scalar_one_or_none()
    if last_ok is None:  # passes are recorded since Stage 6; fall back to samples
        last_ok = session.execute(
            text("SELECT max(sampled_at) FROM player_count_samples")
        ).scalar_one_or_none()
    row = session.execute(
        text(
            """
            SELECT count(*), coalesce(sum(sampled), 0), coalesce(sum(no_data), 0),
                   coalesce(sum(failed), 0)
              FROM player_count_passes WHERE started_at >= :since
            """
        ),
        {"since": now - timedelta(days=days)},
    ).one()
    passes, sampled, no_data, failed = (int(v) for v in row)
    attempted = sampled + no_data + failed
    return {
        "source": "Steam Web API: ISteamUserStats/GetNumberOfCurrentPlayers",
        "last_success_at": last_ok,
        "freshness_hours": round((now - last_ok).total_seconds() / 3600, 1) if last_ok else None,
        "passes_7d": passes,
        "reliability_7d": round((sampled + no_data) / attempted, 4) if attempted else None,
        "failed_calls_7d": failed,
    }


def player_count_coverage(session: Session) -> tuple[date | None, int, int]:
    """(first day with data, days with data, games tracked) for the trending status."""
    row = session.execute(
        text(
            "SELECT min(day), count(DISTINCT day), count(DISTINCT game_id) FROM player_count_daily"
        )
    ).one()
    return row[0], int(row[1] or 0), int(row[2] or 0)


def trend_tracking_game_ids(session: Session, limit: int) -> list[tuple[int, str]]:
    """Games whose player counts we sample: popular discovery sources and well-reviewed
    catalogue games, (game_id, steam_appid), most reviewed first."""
    rows = session.execute(
        text(
            """
            SELECT g.id, e.external_id
              FROM games g
              JOIN external_game_ids e ON e.game_id = g.id AND e.provider = 'steam'
              LEFT JOIN game_review_summaries r ON r.game_id = g.id AND r.source = 'steam_store'
             WHERE g.game_type = 'game' AND g.merged_into_game_id IS NULL
               AND (COALESCE(r.review_count, 0) >= 1000
                    OR EXISTS (SELECT 1 FROM game_discovery_sources d
                                WHERE d.game_id = g.id AND d.source LIKE 'steam_charts%'))
             ORDER BY COALESCE(r.review_count, 0) DESC, g.id
             LIMIT :lim
            """
        ),
        {"lim": limit},
    )
    return [(int(g), str(a)) for g, a in rows]
