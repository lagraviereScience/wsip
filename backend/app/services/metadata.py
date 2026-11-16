"""Steam Store metadata ingestion into the shared catalogue.

Provider failures are contained: a failed batch marks those games' source state
as ``error`` (retried on the next refresh) and never fails a library import.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.integrations.http import ProviderError
from app.integrations.steam.store import MAX_ITEMS_PER_REQUEST, SteamStoreClient, StoreItem
from app.models import Game
from app.repositories import catalogue as catalogue_repo
from app.repositories import library as library_repo
from app.repositories import recommendation as recommendation_repo
from app.repositories import taxonomy as taxonomy_repo
from app.repositories.catalogue import normalize_name
from app.services.taxonomy import RawTag, derive_feature_values
from app.taxonomy.seed import MAPPING_VERSION

logger = logging.getLogger(__name__)

SOURCE = "steam_store"
STEAM_ID_NAMESPACE = "steam"
VOCABULARY_MAX_AGE = timedelta(days=1)


@dataclass(slots=True)
class IngestReport:
    requested: int = 0
    updated: int = 0
    not_found: int = 0
    failed: int = 0


def refresh_vocabulary(session: Session, client: SteamStoreClient) -> tuple[int, int]:
    """Refresh Steam tag and player-category names (ids -> names)."""
    tags = client.get_tag_list()
    categories = client.get_player_categories()
    taxonomy_repo.upsert_provider_tags(session, SOURCE, "tag", {str(k): v for k, v in tags.items()})
    taxonomy_repo.upsert_provider_tags(
        session, SOURCE, "category", {str(k): v for k, v in categories.items()}
    )
    return len(tags), len(categories)


def _rederive(
    session: Session,
    game_id: int,
    mappings: dict[str, dict[str, list[taxonomy_repo.ActiveMapping]]],
) -> None:
    """(Re)compute a game's canonical feature values from its stored raw tags."""
    raw_tags = [
        RawTag(name=r["name"], kind=r["kind"], weight=r["weight"], rank=r["rank"])
        for r in taxonomy_repo.game_raw_tags(session, game_id, SOURCE)
    ]
    derived = derive_feature_values(raw_tags, mappings)
    taxonomy_repo.replace_feature_values(
        session,
        game_id,
        SOURCE,
        [
            {
                "feature_id": fid,
                "value": d.value,
                "confidence": d.confidence,
                "mapping_version": d.mapping_version,
                "evidence": d.evidence,
            }
            for fid, d in derived.items()
        ],
    )


def apply_store_item(session: Session, game_id: int, item: StoreItem) -> None:
    """Write one already-fetched store item into the catalogue (no extra provider call)."""
    mappings = {k: taxonomy_repo.active_mappings(session, SOURCE, k) for k in ("tag", "category")}
    _apply_item(session, game_id, item, mappings, datetime.now(UTC))


def remap_outdated_games(session: Session) -> int:
    """Re-apply the current mapping version to games mapped with an older one.

    Uses stored raw tags only (no provider calls), so a taxonomy/mapping change
    takes effect for the whole catalogue immediately after `sync-taxonomy`.
    """
    mappings = {k: taxonomy_repo.active_mappings(session, SOURCE, k) for k in ("tag", "category")}
    game_ids = catalogue_repo.games_with_outdated_mapping(session, SOURCE, MAPPING_VERSION)
    for gid in game_ids:
        _rederive(session, gid, mappings)
        catalogue_repo.set_source_mapping_version(session, gid, SOURCE, MAPPING_VERSION)
    return len(game_ids)


def ensure_vocabulary(session: Session, client: SteamStoreClient) -> None:
    if taxonomy_repo.vocabulary_size(session, SOURCE, "tag") == 0:
        refresh_vocabulary(session, client)
        session.commit()


def ingest_games(
    session_factory: Callable[[], Session],
    client: SteamStoreClient,
    games: Sequence[tuple[int, str]],
) -> IngestReport:
    """Fetch store metadata for (game_id, steam_appid) pairs, in batches."""
    report = IngestReport(requested=len(games))
    with session_factory() as session:
        try:
            ensure_vocabulary(session, client)
        except ProviderError:
            logger.warning("steam vocabulary unavailable; tags stay unmapped until next refresh")
        mappings = {
            kind: taxonomy_repo.active_mappings(session, SOURCE, kind)
            for kind in ("tag", "category")
        }

    for start in range(0, len(games), MAX_ITEMS_PER_REQUEST):
        batch = list(games[start : start + MAX_ITEMS_PER_REQUEST])
        appid_to_game = {int(appid): gid for gid, appid in batch}
        now = datetime.now(UTC)
        try:
            items = client.get_items(list(appid_to_game))
        except ProviderError as exc:
            logger.warning(
                "store batch failed",
                extra={"provider": SOURCE, "error": exc.code, "batch_size": len(batch)},
            )
            with session_factory() as session:
                for gid, _ in batch:
                    catalogue_repo.record_source(
                        session, gid, SOURCE, "error", now, error_code=exc.code
                    )
                session.commit()
            report.failed += len(batch)
            continue

        with session_factory() as session:
            for item in items:
                gid = appid_to_game[item.appid]
                if not item.found:
                    catalogue_repo.record_source(session, gid, SOURCE, "not_found", now)
                    report.not_found += 1
                    continue
                _apply_item(session, gid, item, mappings, now)
                report.updated += 1
            session.commit()
    return report


def _apply_item(
    session: Session,
    game_id: int,
    item: StoreItem,
    mappings: dict[str, dict[str, list[taxonomy_repo.ActiveMapping]]],
    now: datetime,
) -> None:
    assert item.name is not None
    session.execute(
        update(Game)
        .where(Game.id == game_id)
        .values(
            name=item.name,
            normalized_name=normalize_name(item.name),
            game_type=item.game_type,
            short_description=item.short_description,
            release_date=item.release_date,
            is_free=item.is_free,
            header_image_url=item.header_image_url,
            capsule_image_url=item.capsule_image_url,
            developers=list(item.developers),
            publishers=list(item.publishers),
        )
    )
    tag_ids = taxonomy_repo.provider_tag_ids(
        session, SOURCE, "tag", [str(t.tag_id) for t in item.tags]
    )
    unknown = {
        str(t.tag_id): f"Unknown tag {t.tag_id}" for t in item.tags if str(t.tag_id) not in tag_ids
    }
    if unknown:
        tag_ids.update(taxonomy_repo.upsert_provider_tags(session, SOURCE, "tag", unknown))
    cat_ids = taxonomy_repo.provider_tag_ids(
        session, SOURCE, "category", [str(c) for c in item.category_ids]
    )
    raw_rows = [
        {"provider_tag_id": tag_ids[str(t.tag_id)], "weight": t.weight, "rank": t.rank}
        for t in item.tags
    ] + [{"provider_tag_id": pid, "weight": None, "rank": None} for pid in cat_ids.values()]
    taxonomy_repo.replace_game_provider_tags(session, game_id, SOURCE, raw_rows, now)

    _rederive(session, game_id, mappings)
    library_repo.upsert_review_summary(
        session, game_id, SOURCE, item.review_count, item.review_percent_positive, item.review_label
    )
    if item.country and (item.price is not None or item.is_free):
        price = item.price
        recommendation_repo.upsert_price(
            session,
            game_id,
            item.country,
            is_free=bool(item.is_free),
            final_cents=price.final_cents if price else None,
            original_cents=price.original_cents if price else None,
            discount_pct=price.discount_pct if price else None,
            formatted_final=price.formatted_final if price else None,
            formatted_original=price.formatted_original if price else None,
        )
    catalogue_repo.record_source(
        session, game_id, SOURCE, "ok", now, mapping_version=MAPPING_VERSION
    )
