"""Unowned-candidate discovery and player-count collection (spec §19, §20.3).

Discovery widens the shared catalogue beyond the games users already own, using
only Valve's public store API:

- per user: games carrying the canonical features the player likes most
  (IStoreQueryService/Query by mapped Steam tag, in Steam's popularity order);
- global: Steam's most-played chart and weekly top sellers.

Discovered games get normal store metadata and taxonomy features, and their
provenance is kept in ``game_discovery_sources``.

Player counts are sampled from ISteamUserStats/GetNumberOfCurrentPlayers for a
bounded tracked set and aggregated daily. That self-collected history is the
only input of trend scoring; nothing is scraped from third-party chart sites.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.integrations.http import ProviderError
from app.integrations.steam.store import SteamStoreClient
from app.models.recommendation import PlayerCountPass
from app.repositories import catalogue as catalogue_repo
from app.repositories import recommendation as repo
from app.services import metadata as metadata_service

logger = logging.getLogger(__name__)

STEAM = "steam"
SAMPLE_RETENTION_DAYS = 60


@dataclass(slots=True)
class DiscoveryReport:
    queried: int = 0
    found: int = 0
    new_games: int = 0
    failed_queries: int = 0
    metadata_requested: int = 0


def _register(
    session_factory: Callable[[], Session], appids: list[int], source: str
) -> tuple[list[int], int]:
    """Ensure catalogue rows for appids; record provenance. Returns (game_ids, created)."""
    if not appids:
        return [], 0
    with session_factory() as session:
        ids, created = catalogue_repo.ensure_games(
            session, STEAM, {str(a): None for a in dict.fromkeys(appids)}
        )
        repo.record_discovery(session, ids.values(), source)
        session.commit()
    return list(ids.values()), created


def ingest_missing_metadata(
    session_factory: Callable[[], Session],
    client: SteamStoreClient,
    game_ids: list[int],
    stale_days: int,
) -> int:
    with session_factory() as session:
        due = catalogue_repo.games_needing_metadata_among(
            session,
            STEAM,
            metadata_service.SOURCE,
            datetime.now(UTC) - timedelta(days=stale_days),
            game_ids,
        )
    if due:
        metadata_service.ingest_games(session_factory, client, due)
    return len(due)


def discover_for_user(
    session_factory: Callable[[], Session],
    client: SteamStoreClient,
    user_id: uuid.UUID,
    *,
    max_features: int,
    per_feature: int,
    stale_days: int,
) -> DiscoveryReport:
    """Query Steam for popular games carrying the player's strongest liked features."""
    report = DiscoveryReport()
    with session_factory() as session:
        liked = sorted(
            (
                p
                for p in repo.inferred_preferences(session, user_id)
                if p.value > 0.2 and p.confidence >= 0.2
            ),
            key=lambda p: (-(p.value * p.confidence), p.feature_id),
        )
        manual = [
            m.feature_id for m in repo.manual_preferences(session, user_id) if (m.value or 0) > 0.2
        ]
        feature_ids = list(dict.fromkeys(manual + [p.feature_id for p in liked]))[:max_features]
        tags = repo.steam_tag_ids_for_features(session, feature_ids)
    all_ids: list[int] = []
    for fid in feature_ids:
        tag_list = tags.get(fid)
        if not tag_list:
            continue
        tag = tag_list[0]
        report.queried += 1
        try:
            appids = client.query_by_tags([tag], count=per_feature)
        except ProviderError as exc:
            report.failed_queries += 1
            logger.warning("discovery query failed", extra={"tag": tag, "error": exc.code})
            continue
        ids, created = _register(session_factory, appids, f"steam_query:tag:{tag}")
        report.found += len(ids)
        report.new_games += created
        all_ids += ids
    report.metadata_requested = ingest_missing_metadata(
        session_factory, client, all_ids, stale_days
    )
    return report


def discover_global(
    session_factory: Callable[[], Session], client: SteamStoreClient, *, stale_days: int
) -> DiscoveryReport:
    report = DiscoveryReport()
    all_ids: list[int] = []
    for source, fetch in (
        ("steam_charts:most_played", client.most_played),
        ("steam_charts:top_sellers", client.weekly_top_sellers),
    ):
        report.queried += 1
        try:
            entries = fetch()
        except ProviderError as exc:
            report.failed_queries += 1
            logger.warning("chart discovery failed", extra={"source": source, "error": exc.code})
            continue
        ids, created = _register(session_factory, [e.appid for e in entries], source)
        report.found += len(ids)
        report.new_games += created
        all_ids += ids
    report.metadata_requested = ingest_missing_metadata(
        session_factory, client, all_ids, stale_days
    )
    return report


@dataclass(slots=True)
class SampleReport:
    tracked: int = 0
    sampled: int = 0
    no_data: int = 0
    failed: int = 0


def sample_player_counts(
    session_factory: Callable[[], Session],
    client: SteamStoreClient,
    *,
    max_games: int,
    now: datetime | None = None,
) -> SampleReport:
    """One sampling pass over the tracked set, stored with a shared timestamp."""
    sampled_at = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    with session_factory() as session:
        tracked = repo.trend_tracking_game_ids(session, max_games)
    report = SampleReport(tracked=len(tracked))
    error_code: str | None = None
    counts: dict[int, int] = {}
    for game_id, appid in tracked:
        if not appid.isdigit():
            continue
        try:
            players = client.current_players(int(appid))
        except ProviderError as exc:
            report.failed += 1
            error_code = exc.code
            continue
        if players is None:
            report.no_data += 1
            continue
        counts[game_id] = players
    with session_factory() as session:
        report.sampled = repo.insert_player_counts(session, sampled_at, counts)
        repo.aggregate_player_counts(session, sampled_at.date())
        # Every pass is recorded, failed ones included: source freshness and
        # reliability are measured, not assumed (prompt 6 A).
        session.add(
            PlayerCountPass(
                started_at=sampled_at,
                finished_at=datetime.now(UTC),
                tracked=report.tracked,
                sampled=report.sampled,
                no_data=report.no_data,
                failed=report.failed,
                error_code=error_code if report.failed else None,
            )
        )
        session.commit()
    return report


def aggregate_and_prune(
    session_factory: Callable[[], Session], now: datetime | None = None
) -> None:
    """Finalise yesterday's daily aggregate and drop raw samples past retention."""
    now = now or datetime.now(UTC)
    with session_factory() as session:
        repo.aggregate_player_counts(session, (now - timedelta(days=1)).date())
        repo.aggregate_player_counts(session, now.date())
        repo.prune_player_samples(session, now - timedelta(days=SAMPLE_RETENTION_DAYS))
        session.commit()
