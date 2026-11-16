"""Sign-in-only mode (ADR-0014): users build their library by hand and rate games.

A manually added game is identified by its Steam AppID (validated against the
Steam store), stored in the shared catalogue like any imported game, and enriched
with store metadata and canonical features straight away. Ownership is
self-reported and playtime is unknown (NULL), never zero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.steam.store import SteamStoreClient, StoreItem
from app.models import UserFeedback, UserLibraryEntry
from app.repositories import catalogue as catalogue_repo
from app.services import feedback as feedback_service
from app.services import metadata as metadata_service

PLATFORM = "steam"


class GameNotFound(LookupError):
    """The AppID does not exist on the Steam store or is not a game."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    steam_appid: int
    name: str
    capsule_image_url: str | None
    release_year: int | None
    owned: bool
    rating: int | None


@dataclass(frozen=True, slots=True)
class GameState:
    game_id: int
    steam_appid: int
    name: str
    owned: bool
    rating: int | None


def search(
    session: Session, store: SteamStoreClient, user_id: uuid.UUID, term: str, limit: int = 10
) -> list[SearchResult]:
    """Search the Steam store and annotate results with the user's own state."""
    items = store.search(term, limit=limit)
    known = catalogue_repo.resolve_external_ids(session, PLATFORM, [str(i.appid) for i in items])
    owned_ids, ratings = _user_state(session, user_id, list(known.values()))
    results = []
    for it in items:
        gid = known.get(str(it.appid))
        results.append(
            SearchResult(
                steam_appid=it.appid,
                name=it.name or f"App {it.appid}",
                capsule_image_url=it.capsule_image_url or it.header_image_url,
                release_year=it.release_date.year if it.release_date else None,
                owned=gid in owned_ids if gid else False,
                rating=ratings.get(gid) if gid else None,
            )
        )
    return results


def _user_state(
    session: Session, user_id: uuid.UUID, game_ids: list[int]
) -> tuple[set[int], dict[int, int]]:
    if not game_ids:
        return set(), {}
    owned = set(
        session.execute(
            select(UserLibraryEntry.game_id).where(
                UserLibraryEntry.user_id == user_id,
                UserLibraryEntry.platform == PLATFORM,
                UserLibraryEntry.removed_at.is_(None),
                UserLibraryEntry.game_id.in_(game_ids),
            )
        ).scalars()
    )
    ratings = dict(
        session.execute(
            select(UserFeedback.game_id, UserFeedback.rating).where(
                UserFeedback.user_id == user_id, UserFeedback.game_id.in_(game_ids)
            )
        ).all()
    )
    return owned, ratings


def _store_item(store: SteamStoreClient, appid: int) -> StoreItem:
    item = store.get_items([appid])[0]
    if not item.found or item.game_type != "game":
        raise GameNotFound(appid)
    return item


def set_game_state(
    session: Session,
    store: SteamStoreClient,
    user_id: uuid.UUID,
    appid: int,
    *,
    owned: bool,
    rating: int | None,
) -> GameState:
    """Idempotently set whether the user owns a game and how they rated it.

    ``rating`` None means "not played yet / no opinion" and clears a previous rating.
    A game with neither ownership nor rating is removed from the user's library.
    Raises ``GameNotFound`` and lets ``ProviderError`` propagate (store unavailable).
    """
    gid = catalogue_repo.resolve_external_ids(session, PLATFORM, [str(appid)]).get(str(appid))
    if gid is None:
        item = _store_item(store, appid)
        ids, _ = catalogue_repo.ensure_games(session, PLATFORM, {str(appid): item.name})
        session.commit()  # release the catalogue advisory lock quickly
        gid = ids[str(appid)]
        metadata_service.ensure_vocabulary(session, store)
        metadata_service.apply_store_item(session, gid, item)

    now = datetime.now(UTC)
    entry = session.execute(
        select(UserLibraryEntry).where(
            UserLibraryEntry.user_id == user_id,
            UserLibraryEntry.platform == PLATFORM,
            UserLibraryEntry.game_id == gid,
        )
    ).scalar_one_or_none()
    if owned:
        if entry is None:
            session.add(
                UserLibraryEntry(
                    user_id=user_id,
                    game_id=gid,
                    platform=PLATFORM,
                    source="manual",
                    playtime_forever_minutes=None,
                    playtime_2weeks_minutes=None,
                    last_played_at=None,
                    last_seen_at=now,
                )
            )
        elif entry.removed_at is not None:
            entry.removed_at = None
            entry.last_seen_at = now
    elif entry is not None and entry.source == "manual":
        # Platform-imported ownership is Steam's truth and is never removed by hand.
        session.delete(entry)

    if rating is not None and not -2 <= rating <= 2:
        raise ValueError("rating must be between -2 and 2")
    # Logged in the behaviour event history like every other rating.
    feedback_service.set_satisfaction(
        session, user_id, gid, rating, source="library_entry", now=now
    )
    session.commit()

    owned_ids, ratings = _user_state(session, user_id, [gid])
    name = catalogue_repo.game_name(session, gid) or f"App {appid}"
    return GameState(gid, appid, name, gid in owned_ids, ratings.get(gid))
