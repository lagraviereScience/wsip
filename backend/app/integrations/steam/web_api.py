"""Steam Web API client and the Steam platform adapter.

Endpoints (https://partner.steamgames.com/doc/webapi_overview):
- ISteamUser/GetPlayerSummaries/v2        public profile, visibility
- IPlayerService/GetOwnedGames/v1         owned games, playtime (minutes), last played
- IPlayerService/GetRecentlyPlayedGames/v1  last-two-weeks playtime
- ISteamUserStats/GetPlayerAchievements/v1  achievement progress per app

Steam Web API Terms of Use: 100,000 calls/day per key; user data may be retrieved
only at the user's request; the key must stay confidential (backend only).

Private vs empty libraries: with game details hidden, GetOwnedGames returns
``{"response": {}}`` (no ``game_count``); a visible but empty library returns
``game_count: 0``. A non-public profile (communityvisibilitystate != 3) is
always treated as private.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.integrations.http import ProviderAuthError, ProviderBadResponse, ProviderHttpClient
from app.integrations.platform import (
    AchievementProgress,
    LibrarySnapshot,
    LibraryVisibility,
    OwnedGame,
    PlatformProfile,
)

PROVIDER = "steam_web_api"
PUBLIC_VISIBILITY = 3


class SteamApiKeyMissing(RuntimeError):
    code = "steam_api_key_missing"


class SteamAccountNotFound(RuntimeError):
    code = "steam_account_not_found"


def _ts(value: Any) -> datetime | None:
    if isinstance(value, int) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _minutes(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


class SteamWebApiClient:
    def __init__(self, http: ProviderHttpClient, *, api_key: str | None, base_url: str) -> None:
        self._http = http
        self._key = api_key
        self._base = base_url.rstrip("/")

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        if not self._key:
            raise SteamApiKeyMissing("STEAM_WEB_API_KEY is not configured")
        data = self._http.get_json(f"{self._base}/{path}", {"key": self._key, **params})
        if not isinstance(data, dict):
            raise ProviderBadResponse(PROVIDER, f"{path}: unexpected payload")
        return data

    def get_player_summary(self, steamid: str) -> PlatformProfile:
        data = self._get("ISteamUser/GetPlayerSummaries/v2/", steamids=steamid)
        players = data.get("response", {}).get("players", [])
        player = next((p for p in players if p.get("steamid") == steamid), None)
        if player is None:
            raise SteamAccountNotFound(steamid)
        visibility = player.get("communityvisibilitystate")
        return PlatformProfile(
            external_user_id=steamid,
            display_name=str(player.get("personaname") or "Steam player")[:200],
            profile_url=player.get("profileurl"),
            avatar_url=player.get("avatarfull") or player.get("avatarmedium"),
            visibility=visibility if isinstance(visibility, int) else None,
            profile_is_public=visibility == PUBLIC_VISIBILITY,
        )

    def get_owned_games(self, steamid: str) -> LibrarySnapshot:
        data = self._get(
            "IPlayerService/GetOwnedGames/v1/",
            steamid=steamid,
            include_appinfo=1,
            include_played_free_games=1,
            format="json",
        )
        response = data.get("response")
        if not isinstance(response, dict) or "game_count" not in response:
            return LibrarySnapshot(visibility=LibraryVisibility.PRIVATE, games=())
        games: list[OwnedGame] = []
        for raw in response.get("games") or []:
            appid = raw.get("appid")
            if not isinstance(appid, int) or appid <= 0:
                continue
            name = raw.get("name")
            games.append(
                OwnedGame(
                    external_game_id=str(appid),
                    name=name.strip()[:500] if isinstance(name, str) and name.strip() else None,
                    playtime_forever_minutes=_minutes(raw.get("playtime_forever")),
                    playtime_2weeks_minutes=_minutes(raw.get("playtime_2weeks")),
                    last_played_at=_ts(raw.get("rtime_last_played")),
                )
            )
        visibility = LibraryVisibility.ACCESSIBLE if games else LibraryVisibility.EMPTY
        return LibrarySnapshot(visibility=visibility, games=tuple(games))

    def get_recently_played(self, steamid: str) -> dict[str, int]:
        data = self._get("IPlayerService/GetRecentlyPlayedGames/v1/", steamid=steamid, count=0)
        result: dict[str, int] = {}
        for raw in data.get("response", {}).get("games") or []:
            appid = raw.get("appid")
            if isinstance(appid, int):
                result[str(appid)] = _minutes(raw.get("playtime_2weeks"))
        return result

    def get_player_achievements(self, steamid: str, appid: str) -> AchievementProgress:
        try:
            response = self._http.request(
                "GET",
                f"{self._base}/ISteamUserStats/GetPlayerAchievements/v1/",
                params={"key": self._key, "steamid": steamid, "appid": appid},
            )
        except ProviderAuthError:
            # 403 here means the user's stats are not visible to us.
            return AchievementProgress(status="unavailable", achieved=None, total=None)
        if response.status_code == 400:
            # "Requested app has no stats"
            return AchievementProgress(status="no_stats", achieved=None, total=None)
        if response.status_code != 200:
            return AchievementProgress(status="unavailable", achieved=None, total=None)
        stats = response.json().get("playerstats", {})
        achievements = stats.get("achievements")
        if not stats.get("success") or not isinstance(achievements, list):
            return AchievementProgress(status="no_stats", achieved=None, total=None)
        achieved = sum(1 for a in achievements if a.get("achieved") == 1)
        return AchievementProgress(status="ok", achieved=achieved, total=len(achievements))


class SteamPlatformAdapter:
    """``PlatformAdapter`` for Steam (spec §29)."""

    platform = "steam"

    def __init__(self, client: SteamWebApiClient) -> None:
        self._client = client

    def get_profile(self, external_user_id: str) -> PlatformProfile:
        return self._client.get_player_summary(external_user_id)

    def get_library(self, external_user_id: str) -> LibrarySnapshot:
        return self._client.get_owned_games(external_user_id)

    def get_recent_activity(self, external_user_id: str) -> dict[str, int]:
        return self._client.get_recently_played(external_user_id)

    def get_achievement_progress(
        self, external_user_id: str, external_game_id: str
    ) -> AchievementProgress:
        return self._client.get_player_achievements(external_user_id, external_game_id)
