"""Platform adapter interface (spec §29).

The recommendation engine never talks to a platform directly; it consumes the
platform-independent records below, produced by an adapter. Steam is the only
implementation for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class LibraryVisibility(StrEnum):
    ACCESSIBLE = "accessible"  # library returned with at least one game
    EMPTY = "empty"  # visible, genuinely no games
    PRIVATE = "private"  # game details not visible to us


@dataclass(frozen=True, slots=True)
class PlatformProfile:
    external_user_id: str
    display_name: str
    profile_url: str | None
    avatar_url: str | None
    # Platform-specific visibility code (Steam: 1 private/friends-only, 3 public).
    visibility: int | None
    profile_is_public: bool


@dataclass(frozen=True, slots=True)
class OwnedGame:
    external_game_id: str  # Steam AppID
    name: str | None
    playtime_forever_minutes: int
    playtime_2weeks_minutes: int
    last_played_at: datetime | None


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    visibility: LibraryVisibility
    games: tuple[OwnedGame, ...]


@dataclass(frozen=True, slots=True)
class AchievementProgress:
    status: str  # ok | no_stats | unavailable
    achieved: int | None
    total: int | None


class ProfileSource(Protocol):
    """Anything that can return the public profile of a platform user."""

    def get_profile(self, external_user_id: str) -> PlatformProfile: ...


class PlatformAdapter(Protocol):
    """What each gaming platform must provide (authentication lives in its own module)."""

    platform: str

    def get_profile(self, external_user_id: str) -> PlatformProfile: ...

    def get_library(self, external_user_id: str) -> LibrarySnapshot: ...

    def get_recent_activity(self, external_user_id: str) -> dict[str, int]:
        """Map of external game id -> minutes played in the platform's recent window."""
        ...

    def get_achievement_progress(
        self, external_user_id: str, external_game_id: str
    ) -> AchievementProgress: ...
