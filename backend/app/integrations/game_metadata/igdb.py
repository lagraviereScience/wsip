"""IGDB (Twitch) client for completion times ("time to beat").

Authorised API: https://api-docs.igdb.com/ with Twitch client-credentials OAuth.
Disabled unless the operator sets IGDB_ENABLED, IGDB_CLIENT_ID and
IGDB_CLIENT_SECRET **and** has confirmed IGDB's terms for this site
(docs/PROVIDERS.md: commercial use needs a partnership; OPEN_QUESTIONS #5).

Field names come from IGDB's published protobuf schema
(``https://api.igdb.com/v4/igdbapi.proto``, checked 2026-11-15):

- ``external_games``: ``game``, ``uid``, ``external_game_source`` (1 = Steam);
- ``game_time_to_beats``: ``game_id``, ``hastily``, ``normally``, ``completely``,
  ``count``. IGDB documents the durations in seconds.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.integrations.http import ProviderAuthError, ProviderBadResponse, ProviderHttpClient

API_BASE = "https://api.igdb.com/v4"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"  # noqa: S105 - an endpoint, not a secret
STEAM_SOURCE = 1
BATCH = 200  # IGDB returns at most 500 rows per request


@dataclass(frozen=True, slots=True)
class TimeToBeat:
    igdb_game_id: int
    hastily: int | None
    normally: int | None
    completely: int | None
    count: int | None


def _int_or_none(v: Any) -> int | None:
    return int(v) if isinstance(v, int | float) and v > 0 else None


class IgdbClient:
    def __init__(self, http: ProviderHttpClient, client_id: str, client_secret: str) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires = 0.0

    def _auth(self) -> dict[str, str]:
        if self._token is None or time.monotonic() > self._token_expires - 60:
            response = self._http.request(
                "POST",
                TOKEN_URL,
                # Form body, not the query string: the secret never appears in a URL.
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
            if response.status_code != 200:
                raise ProviderAuthError("igdb", f"token HTTP {response.status_code}")
            body = response.json()
            if not isinstance(body, dict) or "access_token" not in body:
                raise ProviderBadResponse("igdb", "token response without access_token")
            self._token = str(body["access_token"])
            self._token_expires = time.monotonic() + float(body.get("expires_in", 3600))
        return {"Client-ID": self._client_id, "Authorization": f"Bearer {self._token}"}

    def _query(self, endpoint: str, body: str) -> list[dict[str, Any]]:
        response = self._http.request(
            "POST", f"{API_BASE}/{endpoint}", content=body, headers=self._auth()
        )
        if response.status_code != 200:
            raise ProviderBadResponse("igdb", f"{endpoint} HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderBadResponse("igdb", "invalid JSON") from exc
        if not isinstance(data, list):
            raise ProviderBadResponse("igdb", f"{endpoint}: expected a list")
        return [row for row in data if isinstance(row, dict)]

    def steam_games(self, appids: Iterable[str]) -> dict[str, int]:
        """Steam appid -> IGDB game id, for the appids IGDB knows."""
        ids = [a for a in dict.fromkeys(appids) if a.isdigit()]
        out: dict[str, int] = {}
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            uids = ",".join(f'"{a}"' for a in chunk)
            rows = self._query(
                "external_games",
                f"fields game,uid; where external_game_source = {STEAM_SOURCE} "
                f"& uid = ({uids}); limit 500;",
            )
            for row in rows:
                uid, game = row.get("uid"), row.get("game")
                if isinstance(uid, str) and isinstance(game, int):
                    out.setdefault(uid, game)
        return out

    def time_to_beat(self, igdb_ids: Iterable[int]) -> dict[int, TimeToBeat]:
        ids = list(dict.fromkeys(int(i) for i in igdb_ids))
        out: dict[int, TimeToBeat] = {}
        for i in range(0, len(ids), BATCH):
            chunk = ",".join(str(x) for x in ids[i : i + BATCH])
            rows = self._query(
                "game_time_to_beats",
                f"fields game_id,hastily,normally,completely,count; "
                f"where game_id = ({chunk}); limit 500;",
            )
            for row in rows:
                gid = row.get("game_id")
                if not isinstance(gid, int):
                    continue
                out[gid] = TimeToBeat(
                    gid,
                    _int_or_none(row.get("hastily")),
                    _int_or_none(row.get("normally")),
                    _int_or_none(row.get("completely")),
                    _int_or_none(row.get("count")),
                )
        return out
