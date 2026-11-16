"""Completion times ("time to beat") from IGDB, when enabled (prompt 6 B).

Games are looked up by their Steam appid. Rows are stored with source and fetch
time; a game IGDB doesn't know (or has no times for) is stored with NULL values so
it is not asked again until the row is stale. Nothing is estimated or invented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.integrations.game_metadata.igdb import IgdbClient
from app.models.catalogue import GameCompletionTime

SOURCE = "igdb"


@dataclass
class CompletionReport:
    candidates: int = 0
    matched: int = 0
    with_times: int = 0


def due_games(
    session: Session, limit: int, stale_days: int, now: datetime
) -> list[tuple[int, str]]:
    rows = session.execute(
        text(
            """
            SELECT g.id, e.external_id
              FROM games g
              JOIN external_game_ids e ON e.game_id = g.id AND e.provider = 'steam'
              LEFT JOIN game_completion_times c ON c.game_id = g.id AND c.source = :src
             WHERE g.game_type = 'game' AND (c.game_id IS NULL OR c.fetched_at < :stale)
             ORDER BY c.fetched_at NULLS FIRST, g.id
             LIMIT :n
            """
        ),
        {"src": SOURCE, "stale": now - timedelta(days=stale_days), "n": limit},
    ).all()
    return [(int(r[0]), str(r[1])) for r in rows]


def refresh_completion_times(
    session_factory: Callable[[], Session],
    client: IgdbClient,
    *,
    limit: int = 500,
    stale_days: int = 30,
    now: datetime | None = None,
) -> CompletionReport:
    now = now or datetime.now(UTC)
    with session_factory() as session:
        due = due_games(session, limit, stale_days, now)
    report = CompletionReport(candidates=len(due))
    if not due:
        return report
    mapping = client.steam_games(appid for _, appid in due)
    times = client.time_to_beat(mapping.values())
    report.matched = len(mapping)
    rows = []
    for game_id, appid in due:
        igdb_id = mapping.get(appid)
        t = times.get(igdb_id) if igdb_id is not None else None
        if t is not None and any((t.hastily, t.normally, t.completely)):
            report.with_times += 1
        rows.append(
            {
                "game_id": game_id,
                "source": SOURCE,
                "external_id": str(igdb_id) if igdb_id is not None else None,
                "hastily_seconds": t.hastily if t else None,
                "normally_seconds": t.normally if t else None,
                "completely_seconds": t.completely if t else None,
                "submissions": t.count if t else None,
                "fetched_at": now,
            }
        )
    with session_factory() as session:
        stmt = pg_insert(GameCompletionTime).values(rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["game_id", "source"],
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "external_id",
                        "hastily_seconds",
                        "normally_seconds",
                        "completely_seconds",
                        "submissions",
                        "fetched_at",
                    )
                },
            )
        )
        session.commit()
    return report
