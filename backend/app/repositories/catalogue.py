"""Catalogue data access: canonical games, external identifiers, duplicate handling."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import datetime

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    ExternalGameId,
    Game,
    GameFeatureValue,
    GameSource,
    PlaytimeSnapshot,
    UserLibraryEntry,
)

# Serialises creation of new canonical games (advisory lock key, arbitrary constant).
_CATALOGUE_CREATE_LOCK = 724_310_001
_TRADEMARKS = re.compile(r"[™®©]")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    folded = unicodedata.normalize("NFKC", _TRADEMARKS.sub("", name)).casefold()
    return _SPACES.sub(" ", folded).strip()


def canonical_id_expr() -> object:
    return func.coalesce(Game.merged_into_game_id, Game.id)


def game_name(session: Session, game_id: int) -> str | None:
    return session.execute(select(Game.name).where(Game.id == game_id)).scalar_one_or_none()


def resolve_external_ids(
    session: Session, provider: str, external_ids: Iterable[str]
) -> dict[str, int]:
    """External id -> canonical game id (follows merges)."""
    ids = list(external_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(ExternalGameId.external_id, func.coalesce(Game.merged_into_game_id, Game.id))
        .join(Game, Game.id == ExternalGameId.game_id)
        .where(ExternalGameId.provider == provider, ExternalGameId.external_id.in_(ids))
    )
    return {ext: int(gid) for ext, gid in rows}


def ensure_games(
    session: Session, provider: str, items: Mapping[str, str | None]
) -> tuple[dict[str, int], int]:
    """Return canonical ids for every external id, creating missing games once.

    Concurrency-safe: new games are created under a transaction-level advisory
    lock and re-checked after acquiring it, and (provider, external_id) is unique,
    so two users importing the same game at the same time never create duplicates.
    Call in a short transaction; the lock is held until commit.
    """
    found = resolve_external_ids(session, provider, items.keys())
    missing = [ext for ext in items if ext not in found]
    if not missing:
        return found, 0

    session.execute(select(func.pg_advisory_xact_lock(_CATALOGUE_CREATE_LOCK)))
    found.update(resolve_external_ids(session, provider, missing))
    missing = [ext for ext in missing if ext not in found]
    for ext in missing:
        name = items[ext] or f"Unknown {provider} app {ext}"
        game_id = session.execute(
            insert(Game).values(name=name, normalized_name=normalize_name(name)).returning(Game.id)
        ).scalar_one()
        session.execute(
            insert(ExternalGameId).values(game_id=game_id, provider=provider, external_id=ext)
        )
        found[ext] = int(game_id)
    return found, len(missing)


def games_needing_metadata(
    session: Session, provider_id_namespace: str, source: str, stale_before: datetime, limit: int
) -> list[tuple[int, str]]:
    """(game_id, external_id) pairs never fetched from ``source`` or fetched before the cutoff."""
    rows = session.execute(
        select(Game.id, ExternalGameId.external_id)
        .join(ExternalGameId, ExternalGameId.game_id == Game.id)
        .outerjoin(GameSource, (GameSource.game_id == Game.id) & (GameSource.provider == source))
        .where(
            ExternalGameId.provider == provider_id_namespace,
            Game.merged_into_game_id.is_(None),
            (GameSource.id.is_(None)) | (GameSource.fetched_at < stale_before),
        )
        .order_by(GameSource.fetched_at.asc().nulls_first(), Game.id)
        .limit(limit)
    )
    return [(int(g), str(e)) for g, e in rows]


def games_needing_metadata_among(
    session: Session,
    provider_id_namespace: str,
    source: str,
    stale_before: datetime,
    game_ids: list[int],
) -> list[tuple[int, str]]:
    """Like ``games_needing_metadata`` but restricted to the given games."""
    if not game_ids:
        return []
    rows = session.execute(
        select(Game.id, ExternalGameId.external_id)
        .join(ExternalGameId, ExternalGameId.game_id == Game.id)
        .outerjoin(GameSource, (GameSource.game_id == Game.id) & (GameSource.provider == source))
        .where(
            Game.id.in_(game_ids),
            ExternalGameId.provider == provider_id_namespace,
            (GameSource.id.is_(None)) | (GameSource.fetched_at < stale_before),
        )
        .order_by(Game.id)
    )
    return [(int(g), str(e)) for g, e in rows]


def record_source(
    session: Session,
    game_id: int,
    provider: str,
    status: str,
    fetched_at: datetime,
    *,
    mapping_version: int | None = None,
    error_code: str | None = None,
) -> None:
    stmt = pg_insert(GameSource).values(
        game_id=game_id,
        provider=provider,
        status=status,
        fetched_at=fetched_at,
        mapping_version=mapping_version,
        error_code=error_code,
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[GameSource.game_id, GameSource.provider],
            set_={
                "status": stmt.excluded.status,
                "fetched_at": stmt.excluded.fetched_at,
                "mapping_version": stmt.excluded.mapping_version,
                "error_code": stmt.excluded.error_code,
            },
        )
    )


def games_with_outdated_mapping(session: Session, source: str, version: int) -> list[int]:
    rows = session.execute(
        select(GameSource.game_id).where(
            GameSource.provider == source,
            GameSource.status == "ok",
            (GameSource.mapping_version.is_(None)) | (GameSource.mapping_version < version),
        )
    ).scalars()
    return [int(r) for r in rows]


def set_source_mapping_version(session: Session, game_id: int, source: str, version: int) -> None:
    session.execute(
        update(GameSource)
        .where(GameSource.game_id == game_id, GameSource.provider == source)
        .values(mapping_version=version)
    )


def merge_games(session: Session, source_id: int, target_id: int) -> None:
    """Merge a duplicate game into the surviving canonical record.

    External ids, library entries (with their snapshots) and feature values move to
    the target; the source row stays as a tombstone pointing at the target so old
    references still resolve. Where a user owns both, the entry with more playtime
    survives and the other's snapshots are re-pointed to it.
    """
    if source_id == target_id:
        raise ValueError("cannot merge a game into itself")
    target = session.get(Game, target_id)
    if target is None or target.merged_into_game_id is not None:
        raise ValueError("target must be an existing canonical game")

    session.execute(
        update(ExternalGameId).where(ExternalGameId.game_id == source_id).values(game_id=target_id)
    )

    # Library entries owned under both ids: keep the one with more playtime.
    pairs = session.execute(
        text(
            """
            SELECT s.id AS src, t.id AS tgt,
                   s.playtime_forever_minutes > t.playtime_forever_minutes AS src_wins
            FROM user_library s
            JOIN user_library t ON t.user_id = s.user_id AND t.platform = s.platform
            WHERE s.game_id = :src AND t.game_id = :tgt
            """
        ),
        {"src": source_id, "tgt": target_id},
    ).all()
    for src_entry, tgt_entry, src_wins in pairs:
        keep, drop = (src_entry, tgt_entry) if src_wins else (tgt_entry, src_entry)
        session.execute(
            update(PlaytimeSnapshot)
            .where(PlaytimeSnapshot.library_entry_id == drop)
            .values(library_entry_id=keep)
        )
        session.execute(
            text("DELETE FROM achievement_summaries WHERE library_entry_id = :d"), {"d": drop}
        )
        session.execute(text("DELETE FROM user_library WHERE id = :d"), {"d": drop})
    session.execute(
        update(UserLibraryEntry)
        .where(UserLibraryEntry.game_id == source_id)
        .values(game_id=target_id)
    )

    session.execute(
        text(
            """
            INSERT INTO game_feature_values
                (game_id, feature_id, source, value, confidence, mapping_version, evidence)
            SELECT :tgt, feature_id, source, value, confidence, mapping_version, evidence
            FROM game_feature_values WHERE game_id = :src
            ON CONFLICT DO NOTHING
            """
        ),
        {"src": source_id, "tgt": target_id},
    )
    session.execute(delete(GameFeatureValue).where(GameFeatureValue.game_id == source_id))
    # Earlier merges into the source now point straight at the target.
    session.execute(
        update(Game)
        .where(Game.merged_into_game_id == source_id)
        .values(merged_into_game_id=target_id)
    )
    session.execute(update(Game).where(Game.id == source_id).values(merged_into_game_id=target_id))
