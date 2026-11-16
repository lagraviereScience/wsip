"""Platform library import (runs in a background worker).

Flow for one ``LibrarySyncRun``:
1. Fetch profile + owned games from the platform adapter.
2. Private game details -> run ``blocked_private``; no library rows are written,
   so no misleading empty profile can be built (onboarding asks the user to fix it).
   Visible but empty library -> run ``empty``.
3. Resolve every game to the shared catalogue (no duplicates across users).
4. Upsert library entries; append a playtime snapshot for new entries and for any
   change in reported values (append-only, platform-reported values only).
5. Best effort: achievements for recently played games, then queue metadata
   ingestion. Failures here never fail the import (spec: provider failures must
   not break Steam integration).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.integrations.http import ProviderError
from app.integrations.platform import LibraryVisibility, OwnedGame, PlatformAdapter
from app.integrations.steam.web_api import SteamAccountNotFound, SteamApiKeyMissing
from app.models import LibrarySyncRun, PlaytimeSnapshot, UserLibraryEntry
from app.repositories import behaviour as behaviour_repo
from app.repositories import catalogue as catalogue_repo
from app.repositories import library as library_repo
from app.repositories import users as users_repo

logger = logging.getLogger(__name__)

# Heuristic for Steam's "Always keep my total playtime private" option: games are
# visible but every playtime is reported as zero.
HIDDEN_PLAYTIME_MIN_GAMES = 5


@dataclass(frozen=True, slots=True)
class ImportResult:
    status: str
    games_seen: int = 0
    games_new_to_catalogue: int = 0
    snapshots_written: int = 0
    error_code: str | None = None
    game_ids: tuple[int, ...] = ()


def _finish(
    session: Session,
    run: LibrarySyncRun,
    status: str,
    *,
    error_code: str | None = None,
    detail: str | None = None,
) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.error_code = error_code
    run.error_detail = detail[:500] if detail else None


def _merge_duplicates(games: tuple[OwnedGame, ...], ids: dict[str, int]) -> dict[int, OwnedGame]:
    """Two platform ids can resolve to one canonical game (after a merge): keep the richer."""
    by_game: dict[int, OwnedGame] = {}
    for g in games:
        gid = ids[g.external_game_id]
        current = by_game.get(gid)
        if current is None or g.playtime_forever_minutes > current.playtime_forever_minutes:
            by_game[gid] = g
    return by_game


def run_library_import(
    session_factory: Callable[[], Session],
    adapter: PlatformAdapter,
    run_id: int,
    *,
    achievements_limit: int = 10,
) -> ImportResult:
    now = datetime.now(UTC)
    with session_factory() as session:
        run = session.get(LibrarySyncRun, run_id)
        if run is None or run.status != "queued":
            logger.info("sync run not runnable", extra={"run_id": run_id})
            return ImportResult(status="skipped")
        link = users_repo.platform_link(session, run.user_id, run.platform)
        if link is None:
            _finish(session, run, "failed", error_code="platform_not_connected")
            session.commit()
            return ImportResult(status="failed", error_code="platform_not_connected")
        run.status, run.started_at = "running", now
        user_id: uuid.UUID = run.user_id
        platform, external_user_id = run.platform, link.external_user_id
        session.commit()

    try:
        profile = adapter.get_profile(external_user_id)
        library = adapter.get_library(external_user_id)
    except (SteamApiKeyMissing, SteamAccountNotFound, ProviderError) as exc:
        code = getattr(exc, "code", "provider_error")
        logger.warning("library import failed", extra={"run_id": run_id, "error": code})
        with session_factory() as session:
            run = session.get_one(LibrarySyncRun, run_id)
            _finish(session, run, "failed", error_code=code)
            link = users_repo.platform_link(session, user_id, platform)
            if link is not None and link.game_details_status == "unknown":
                link.game_details_status = "error"
            session.commit()
        return ImportResult(status="failed", error_code=code)

    with session_factory() as session:
        run = session.get_one(LibrarySyncRun, run_id)
        link = users_repo.platform_link(session, user_id, platform)
        assert link is not None
        user = link.user
        users_repo.apply_profile(user, link, profile)
        link.game_details_checked_at = datetime.now(UTC)

        if not profile.profile_is_public or library.visibility is LibraryVisibility.PRIVATE:
            link.game_details_status = "private"
            _finish(session, run, "blocked_private", error_code="game_details_private")
            session.commit()
            return ImportResult(status="blocked_private", error_code="game_details_private")
        if library.visibility is LibraryVisibility.EMPTY:
            link.game_details_status = "empty"
            link.last_synced_at = datetime.now(UTC)
            run.games_seen = 0
            _finish(session, run, "empty")
            session.commit()
            return ImportResult(status="empty")

        # Short transaction: creating catalogue games takes a global advisory lock.
        ids, created = catalogue_repo.ensure_games(
            session, platform, {g.external_game_id: g.name for g in library.games}
        )
        session.commit()

    try:
        recent = adapter.get_recent_activity(external_user_id)
    except ProviderError as exc:
        logger.info("recent activity unavailable", extra={"error": exc.code})
        recent = {}

    synced_at = datetime.now(UTC)
    snapshots = 0
    by_game = _merge_duplicates(library.games, ids)
    with session_factory() as session:
        run = session.get_one(LibrarySyncRun, run_id)
        entries = library_repo.library_entries(session, user_id, platform)
        # Playtime growth since the previous sync: behavioural evidence (spec §21).
        # Not on the first import, where every game would "grow" from nothing.
        had_library = any(e.source == "steam_import" for e in entries.values())
        growth: dict[int, tuple[int, int, bool]] = {}
        for gid, g in by_game.items():
            two_weeks = max(g.playtime_2weeks_minutes, recent.get(g.external_game_id, 0))
            entry = entries.get(gid)
            if entry is None:
                entry = UserLibraryEntry(
                    user_id=user_id,
                    game_id=gid,
                    platform=platform,
                    playtime_forever_minutes=g.playtime_forever_minutes,
                    playtime_2weeks_minutes=two_weeks,
                    last_played_at=g.last_played_at,
                    last_seen_at=synced_at,
                )
                session.add(entry)
                session.flush()
                changed = True
                if had_library and g.playtime_forever_minutes > 0:
                    growth[gid] = (g.playtime_forever_minutes, g.playtime_forever_minutes, True)
            else:
                old = entry.playtime_forever_minutes
                if old is not None and g.playtime_forever_minutes > old:
                    growth[gid] = (
                        g.playtime_forever_minutes - old,
                        g.playtime_forever_minutes,
                        False,
                    )
                changed = (
                    entry.playtime_forever_minutes != g.playtime_forever_minutes
                    or entry.playtime_2weeks_minutes != two_weeks
                    or entry.last_played_at != g.last_played_at
                    or entry.removed_at is not None
                )
                entry.source = "steam_import"  # platform data supersedes a manual entry
                entry.playtime_forever_minutes = g.playtime_forever_minutes
                entry.playtime_2weeks_minutes = two_weeks
                entry.last_played_at = g.last_played_at
                entry.removed_at = None
                entry.last_seen_at = synced_at
            if changed:
                session.add(
                    PlaytimeSnapshot(
                        library_entry_id=entry.id,
                        sync_run_id=run_id,
                        captured_at=synced_at,
                        playtime_forever_minutes=g.playtime_forever_minutes,
                        playtime_2weeks_minutes=two_weeks,
                        last_played_at=g.last_played_at,
                    )
                )
                snapshots += 1
        for gid, entry in entries.items():
            if gid not in by_game and entry.removed_at is None and entry.source == "steam_import":
                entry.removed_at = synced_at
        _record_playtime_growth(session, user_id, run_id, growth, synced_at)

        link = users_repo.platform_link(session, user_id, platform)
        assert link is not None
        link.game_details_status = "accessible"
        link.last_synced_at = synced_at
        link.playtime_appears_hidden = len(by_game) >= HIDDEN_PLAYTIME_MIN_GAMES and all(
            g.playtime_forever_minutes == 0 for g in by_game.values()
        )
        run.games_seen = len(by_game)
        run.games_new = created
        run.snapshots_written = snapshots
        _finish(session, run, "succeeded")
        session.commit()
        entry_ids = {
            gid: e.id for gid, e in library_repo.library_entries(session, user_id, platform).items()
        }

    _import_achievements(
        session_factory, adapter, external_user_id, by_game, entry_ids, achievements_limit
    )
    return ImportResult(
        status="succeeded",
        games_seen=len(by_game),
        games_new_to_catalogue=created,
        snapshots_written=snapshots,
        game_ids=tuple(by_game),
    )


EXPOSURE_ATTRIBUTION_WINDOW = timedelta(days=90)


def _record_playtime_growth(
    session: Session,
    user_id: uuid.UUID,
    run_id: int,
    growth: dict[int, tuple[int, int, bool]],
    at: datetime,
) -> None:
    """Append ``playtime_change`` events, attributed to the latest recommendation
    exposure of each game within 90 days (so outcomes link to the model)."""
    if not growth:
        return
    exposures = behaviour_repo.last_exposures(
        session, user_id, growth, at - EXPOSURE_ATTRIBUTION_WINDOW
    )
    rows = []
    for gid, (delta, total, new_game) in growth.items():
        ex = exposures.get(gid, {})
        rows.append(
            {
                "user_id": user_id,
                "game_id": gid,
                "feature_id": None,
                "event_type": "playtime_change",
                "occurred_at": at,
                "idempotency_key": f"playtime:{run_id}:{gid}",
                "recommendation_run_id": ex.get("recommendation_run_id"),
                "category": ex.get("category"),
                "position": ex.get("position"),
                "model_version": ex.get("model_version"),
                "surface": None,
                "context": {},
                "event_metadata": {
                    "delta_minutes": delta,
                    "total_minutes": total,
                    "sync_run_id": run_id,
                    "newly_owned": new_game,
                },
            }
        )
    behaviour_repo.insert_events(session, rows)


def _import_achievements(
    session_factory: Callable[[], Session],
    adapter: PlatformAdapter,
    external_user_id: str,
    by_game: dict[int, OwnedGame],
    entry_ids: dict[int, int],
    limit: int,
) -> None:
    """Achievement progress for the most recently played games only (bounded cost)."""
    recent = sorted(
        (gid for gid, g in by_game.items() if g.playtime_2weeks_minutes > 0),
        key=lambda gid: by_game[gid].playtime_2weeks_minutes,
        reverse=True,
    )[:limit]
    for gid in recent:
        try:
            progress = adapter.get_achievement_progress(
                external_user_id, by_game[gid].external_game_id
            )
        except ProviderError as exc:
            logger.info("achievements unavailable", extra={"error": exc.code})
            return
        with session_factory() as session:
            library_repo.upsert_achievement_summary(
                session, entry_ids[gid], progress.status, progress.achieved, progress.total
            )
            session.commit()
