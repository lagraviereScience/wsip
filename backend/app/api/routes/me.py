"""The signed-in user's own data. Never exposes another user's data (spec §23, §34)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.rate_limit import FixedWindowLimiter
from app.database.redis import get_redis
from app.integrations import factory
from app.integrations.http import ProviderError
from app.repositories import library as library_repo
from app.repositories import users as users_repo
from app.schemas.me import (
    GameStateIn,
    GameStateOut,
    LibraryGameOut,
    LibraryOut,
    LibraryStatsOut,
    MeOut,
    SearchOut,
    SearchResultOut,
    SteamConnectionOut,
    SyncRunOut,
)
from app.services import manual_library
from app.workers.tasks import import_library

router = APIRouter(prefix="/me", tags=["me"])


def _me(db: DbSession, user: CurrentUser, settings: AppSettings) -> MeOut:
    link = users_repo.platform_link(db, user.id, "steam")
    run = library_repo.latest_sync_run(db, user.id, "steam")
    steam = None
    if link is not None:
        steam = SteamConnectionOut(
            steam_id=link.external_user_id,
            profile_name=link.profile_name,
            profile_url=link.profile_url,
            avatar_url=link.avatar_url,
            profile_is_public=None
            if link.profile_visibility is None
            else link.profile_visibility == 3,
            game_details_status=link.game_details_status,
            game_details_checked_at=link.game_details_checked_at,
            playtime_appears_hidden=link.playtime_appears_hidden,
            last_synced_at=link.last_synced_at,
        )
    stats = LibraryStatsOut(**library_repo.library_stats(db, user.id, "steam"))
    mode = settings.library_mode
    if mode == "manual":
        ready = stats.games_rated >= settings.min_rated_games_for_profile
    else:
        ready = steam is not None and steam.game_details_status == "accessible"
    return MeOut(
        id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        steam=steam,
        latest_sync=SyncRunOut.model_validate(run, from_attributes=True) if run else None,
        library=stats,
        library_mode=mode,
        min_rated_games=settings.min_rated_games_for_profile,
        profile_ready=ready,
    )


@router.get("", response_model=MeOut)
def get_me(db: DbSession, user: CurrentUser, settings: AppSettings) -> MeOut:
    return _me(db, user, settings)


@router.post("/steam/sync", response_model=MeOut, status_code=status.HTTP_202_ACCEPTED)
def request_sync(db: DbSession, user: CurrentUser, settings: AppSettings) -> MeOut:
    """Re-check game-details visibility and re-import the library (onboarding retry)."""
    if settings.library_mode != "steam_import":
        raise HTTPException(status.HTTP_409_CONFLICT, "Automatic Steam import is not enabled")
    if users_repo.platform_link(db, user.id, "steam") is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No Steam account connected")
    run, created = library_repo.enqueue_sync_run(db, user.id, "steam", "manual")
    db.commit()
    if created:
        import_library.delay(run.id)
    return _me(db, user, settings)


@router.get("/library", response_model=LibraryOut)
def get_library(db: DbSession, user: CurrentUser) -> LibraryOut:
    rows = library_repo.library_view(db, user.id, "steam")
    return LibraryOut(
        games=[
            LibraryGameOut(
                game_id=r["game_id"],
                name=r["name"],
                steam_appid=r["steam_appid"],
                header_image_url=r["header_image_url"],
                capsule_image_url=r["capsule_image_url"],
                game_type=r["game_type"],
                release_date=r["release_date"],
                owned=r["owned"],
                ownership_source=r["ownership_source"],
                rating=r["rating"],
                playtime_forever_minutes=r["playtime_forever_minutes"],
                playtime_2weeks_minutes=r["playtime_2weeks_minutes"],
                last_played_at=r["last_played_at"],
                achievements_achieved=r["achieved"],
                achievements_total=r["achievements_total"],
                review_label=r["review_label"],
                top_features=list(r["top_features"] or []),
            )
            for r in rows
        ]
    )


_STORE_UNAVAILABLE = "Steam's store didn't respond. Please try again in a moment."


@router.get("/library/search", response_model=SearchOut)
def search_games(
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> SearchOut:
    """Search Steam's store for games to add (results annotated with the user's state)."""
    limit = FixedWindowLimiter(get_redis(), "library-search", settings.library_search_per_minute)
    if not limit.hit(str(user.id)).allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many searches; slow down.")
    try:
        results = manual_library.search(
            db, factory.steam_store_client(settings), user.id, q.strip()
        )
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _STORE_UNAVAILABLE) from exc
    return SearchOut(results=[SearchResultOut(**asdict(r)) for r in results])


@router.put("/library/games/{steam_appid}", response_model=GameStateOut)
def set_game(
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    steam_appid: Annotated[int, Path(ge=1, le=2_147_483_647)],
    body: GameStateIn,
) -> GameStateOut:
    """Set whether the user owns a game and their rating (null = not played / no opinion)."""
    try:
        state = manual_library.set_game_state(
            db,
            factory.steam_store_client(settings),
            user.id,
            steam_appid,
            owned=body.owned,
            rating=body.rating,
        )
    except manual_library.GameNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such game on the Steam store") from exc
    except ProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _STORE_UNAVAILABLE) from exc
    return GameStateOut(**asdict(state))
