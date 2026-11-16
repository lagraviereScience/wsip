from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SyncRunOut(BaseModel):
    id: int
    status: Literal["queued", "running", "succeeded", "blocked_private", "empty", "failed"]
    trigger: str
    queued_at: datetime
    finished_at: datetime | None
    games_seen: int | None
    error_code: str | None


class SteamConnectionOut(BaseModel):
    steam_id: str
    profile_name: str | None
    profile_url: str | None
    avatar_url: str | None
    profile_is_public: bool | None
    game_details_status: Literal["unknown", "accessible", "empty", "private", "error"]
    game_details_checked_at: datetime | None
    playtime_appears_hidden: bool
    last_synced_at: datetime | None


class LibraryStatsOut(BaseModel):
    games_owned: int
    games_played: int
    games_rated: int
    total_playtime_minutes: int
    recent_playtime_minutes: int


class MeOut(BaseModel):
    id: uuid.UUID
    display_name: str
    avatar_url: str | None
    steam: SteamConnectionOut | None
    latest_sync: SyncRunOut | None
    library: LibraryStatsOut
    # "manual": sign-in only, users add and rate games (ADR-0014).
    # "steam_import": library read from the Steam Web API.
    library_mode: Literal["manual", "steam_import"]
    min_rated_games: int
    # Onboarding gate: steam_import needs accessible game details; manual needs
    # at least ``min_rated_games`` rated games.
    profile_ready: bool


class LibraryGameOut(BaseModel):
    game_id: int
    name: str
    steam_appid: str | None
    header_image_url: str | None
    capsule_image_url: str | None
    game_type: str
    release_date: date | None
    owned: bool
    ownership_source: Literal["steam_import", "manual"] | None
    # Loved=2, Liked=1, Neutral=0, Disliked=-1, Hated=-2; None = not rated.
    rating: int | None
    # None = unknown (manual entries); 0 = reported as never played.
    playtime_forever_minutes: int | None
    playtime_2weeks_minutes: int | None
    last_played_at: datetime | None
    achievements_achieved: int | None
    achievements_total: int | None
    review_label: str | None
    top_features: list[str]


class LibraryOut(BaseModel):
    games: list[LibraryGameOut]
    attribution: str = "Game data provided by Steam."


class GameStateIn(BaseModel):
    owned: bool
    rating: int | None = Field(default=None, ge=-2, le=2)


class GameStateOut(BaseModel):
    game_id: int
    steam_appid: int
    name: str
    owned: bool
    rating: int | None


class SearchResultOut(BaseModel):
    steam_appid: int
    name: str
    capsule_image_url: str | None
    release_year: int | None
    owned: bool
    rating: int | None


class SearchOut(BaseModel):
    results: list[SearchResultOut]
    attribution: str = "Search results provided by Steam."
