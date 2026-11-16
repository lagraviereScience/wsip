"""Steam Store metadata via the public IStoreBrowseService / IStoreService endpoints.

These endpoints serve the same data as the Steam store pages through Valve's own
API (no scraping, no key required):
- IStoreBrowseService/GetItems/v1           name, type, description, release, assets,
                                            categories, user tags with vote weights, reviews
- IStoreService/GetTagList/v1               tag id -> English name
- IStoreBrowseService/GetStoreCategories/v1 category id -> name
- IStoreQueryService/Query/v1               games carrying given tags, in Steam's own
                                            popularity order (candidate discovery)
- ISteamChartsService/GetMostPlayedGames/v1 Steam's public most-played chart
- IStoreTopSellersService/GetWeeklyTopSellers/v1  Steam's public weekly top sellers
- ISteamUserStats/GetNumberOfCurrentPlayers/v1    current players of one app

Displayed Steam data must be attributed to Steam (Steam Web API Terms of Use).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.integrations.http import ProviderBadResponse, ProviderHttpClient

PROVIDER = "steam_store"
MAX_ITEMS_PER_REQUEST = 50

# EStoreAppType as returned in store_items[].type.
_STORE_APP_TYPES = {
    0: "game",
    1: "demo",
    2: "mod",
    3: "video",
    4: "dlc",
    5: "guide",
    6: "software",
    7: "video",
    8: "video",
    9: "video",
    10: "hardware",
    11: "music",
    12: "beta",
    13: "tool",
    14: "advertising",
}


@dataclass(frozen=True, slots=True)
class StoreTag:
    tag_id: int
    weight: int
    rank: int


@dataclass(frozen=True, slots=True)
class StoreItem:
    appid: int
    found: bool
    name: str | None = None
    game_type: str = "unknown"
    short_description: str | None = None
    release_date: date | None = None
    is_free: bool | None = None
    header_image_url: str | None = None
    capsule_image_url: str | None = None
    developers: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    tags: tuple[StoreTag, ...] = ()
    category_ids: tuple[int, ...] = ()
    review_count: int | None = None
    review_percent_positive: int | None = None
    review_label: str | None = None
    price: StorePrice | None = None
    country: str | None = None  # storefront country the price applies to


@dataclass(frozen=True, slots=True)
class StorePrice:
    """best_purchase_option of a store item, for the client's storefront country."""

    final_cents: int | None
    original_cents: int | None
    discount_pct: int | None
    formatted_final: str | None
    formatted_original: str | None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_price(it: dict[str, Any]) -> StorePrice | None:
    bpo = it.get("best_purchase_option")
    if not isinstance(bpo, dict):
        return None
    final = _int_or_none(bpo.get("final_price_in_cents"))
    original = _int_or_none(bpo.get("original_price_in_cents"))
    pct = _int_or_none(bpo.get("discount_pct"))
    if pct is None and final is not None and original and original > final:
        pct = round(100 * (original - final) / original)
    fmt_final = bpo.get("formatted_final_price")
    fmt_orig = bpo.get("formatted_original_price")
    return StorePrice(
        final_cents=final,
        original_cents=original,
        discount_pct=pct,
        formatted_final=str(fmt_final)[:32] if isinstance(fmt_final, str) else None,
        formatted_original=str(fmt_orig)[:32] if isinstance(fmt_orig, str) else None,
    )


@dataclass(frozen=True, slots=True)
class ChartEntry:
    appid: int
    rank: int
    players: int | None  # concurrent or peak players, as the chart reports them


class SteamStoreClient:
    def __init__(
        self,
        http: ProviderHttpClient,
        *,
        base_url: str,
        asset_base_url: str,
        country: str = "US",
        language: str = "english",
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._asset_base = asset_base_url
        self._country = country
        self._language = language

    def get_items(self, appids: list[int]) -> list[StoreItem]:
        if not appids:
            return []
        if len(appids) > MAX_ITEMS_PER_REQUEST:
            raise ValueError(f"at most {MAX_ITEMS_PER_REQUEST} appids per request")
        query = {
            "ids": [{"appid": a} for a in appids],
            "context": {"language": self._language, "country_code": self._country},
            "data_request": {
                "include_basic_info": True,
                "include_tag_count": 20,
                "include_release": True,
                "include_assets": True,
                "include_categories": True,
                "include_reviews": True,
            },
        }
        data = self._http.get_json(
            f"{self._base}/IStoreBrowseService/GetItems/v1/",
            {"input_json": json.dumps(query, separators=(",", ":"))},
        )
        raw_items = (data or {}).get("response", {}).get("store_items")
        if not isinstance(raw_items, list):
            raise ProviderBadResponse(PROVIDER, "GetItems: missing store_items")
        by_id = {it.get("id"): it for it in raw_items if isinstance(it, dict)}
        return [self._parse_item(appid, by_id.get(appid)) for appid in appids]

    def _asset(self, assets: dict[str, Any], key: str) -> str | None:
        fmt, filename = assets.get("asset_url_format"), assets.get(key)
        if not isinstance(fmt, str) or not isinstance(filename, str):
            return None
        return self._asset_base + fmt.replace("${FILENAME}", filename)

    def _parse_item(self, appid: int, it: dict[str, Any] | None) -> StoreItem:
        if not it or it.get("success") != 1 or not it.get("name"):
            return StoreItem(appid=appid, found=False)
        basic = it.get("basic_info") or {}
        release_ts = (it.get("release") or {}).get("steam_release_date")
        tags_raw = it.get("tags") or []
        tags = tuple(
            StoreTag(tag_id=int(t["tagid"]), weight=int(t.get("weight") or 0), rank=i)
            for i, t in enumerate(tags_raw)
            if isinstance(t, dict) and isinstance(t.get("tagid"), int)
        )
        cats = it.get("categories") or {}
        summary = (it.get("reviews") or {}).get("summary_filtered") or {}
        assets = it.get("assets") or {}
        return StoreItem(
            appid=appid,
            found=True,
            name=str(it["name"])[:500],
            game_type=_STORE_APP_TYPES.get(raw_type, "unknown")
            if isinstance(raw_type := it.get("type"), int)
            else "unknown",
            short_description=basic.get("short_description"),
            release_date=(
                datetime.fromtimestamp(release_ts, tz=UTC).date()
                if isinstance(release_ts, int) and release_ts > 0
                else None
            ),
            is_free=it.get("is_free") is True,
            header_image_url=self._asset(assets, "header"),
            capsule_image_url=self._asset(assets, "main_capsule"),
            developers=tuple(d["name"] for d in basic.get("developers") or [] if d.get("name")),
            publishers=tuple(p["name"] for p in basic.get("publishers") or [] if p.get("name")),
            tags=tags,
            category_ids=tuple(
                c for c in cats.get("supported_player_categoryids") or [] if isinstance(c, int)
            ),
            review_count=summary.get("review_count"),
            review_percent_positive=summary.get("percent_positive"),
            review_label=summary.get("review_score_label"),
            price=_parse_price(it),
            country=self._country,
        )

    def search(self, term: str, limit: int = 10) -> list[StoreItem]:
        """Store search suggestions (IStoreQueryService/SearchSuggestions), games only."""
        query = {
            "search_term": term,
            "max_results": min(max(limit * 2, 10), 50),  # over-fetch: DLC/soundtracks are dropped
            "context": {"language": self._language, "country_code": self._country},
            "data_request": {
                "include_basic_info": True,
                "include_assets": True,
                "include_release": True,
            },
        }
        data = self._http.get_json(
            f"{self._base}/IStoreQueryService/SearchSuggestions/v1/",
            {"input_json": json.dumps(query, separators=(",", ":"))},
        )
        raw_items = (data or {}).get("response", {}).get("store_items") or []
        if not isinstance(raw_items, list):
            raise ProviderBadResponse(PROVIDER, "SearchSuggestions: bad store_items")
        items = [
            self._parse_item(int(it["id"]), it)
            for it in raw_items
            if isinstance(it, dict) and isinstance(it.get("id"), int)
        ]
        return [i for i in items if i.found and i.game_type == "game"][:limit]

    def query_by_tags(self, tag_ids: list[int], *, count: int = 50, sort: int = 12) -> list[int]:
        """AppIDs of released games carrying ALL of ``tag_ids`` (IStoreQueryService/Query).

        ``sort=12`` is Steam's own popularity ordering (undocumented enum, verified
        2026-11-15 to return widely reviewed games first). Metadata for the returned
        apps is fetched separately through ``get_items``.
        """
        query = {
            "query": {
                "start": 0,
                "count": max(1, min(count, 100)),
                "sort": sort,
                "filters": {
                    "released_only": True,
                    "type_filters": {"include_games": True},
                    "tagids_must_match": [{"tagids": [t]} for t in tag_ids],
                },
            },
            "context": {"language": self._language, "country_code": self._country},
            "data_request": {"include_basic_info": False},
        }
        data = self._http.get_json(
            f"{self._base}/IStoreQueryService/Query/v1/",
            {"input_json": json.dumps(query, separators=(",", ":"))},
        )
        response = (data or {}).get("response")
        if not isinstance(response, dict):
            raise ProviderBadResponse(PROVIDER, "Query: missing response")
        ids = response.get("ids") or response.get("store_items") or []
        out: list[int] = []
        for it in ids if isinstance(ids, list) else []:
            appid = it.get("appid") or it.get("id") if isinstance(it, dict) else None
            if isinstance(appid, int) and appid > 0:
                out.append(appid)
        return out

    def most_played(self) -> list[ChartEntry]:
        """Steam's public most-played chart (top 100, peak players in the last day)."""
        data = self._http.get_json(f"{self._base}/ISteamChartsService/GetMostPlayedGames/v1/", {})
        ranks = (data or {}).get("response", {}).get("ranks")
        if not isinstance(ranks, list):
            raise ProviderBadResponse(PROVIDER, "GetMostPlayedGames: missing ranks")
        return [
            ChartEntry(
                int(r["appid"]), int(r.get("rank") or 0), _int_or_none(r.get("peak_in_game"))
            )
            for r in ranks
            if isinstance(r, dict) and isinstance(r.get("appid"), int)
        ]

    def weekly_top_sellers(self, page_count: int = 100) -> list[ChartEntry]:
        query = {
            "country_code": self._country,
            "context": {"language": self._language, "country_code": self._country},
            "page_count": page_count,
        }
        data = self._http.get_json(
            f"{self._base}/IStoreTopSellersService/GetWeeklyTopSellers/v1/",
            {"input_json": json.dumps(query, separators=(",", ":"))},
        )
        ranks = (data or {}).get("response", {}).get("ranks")
        if not isinstance(ranks, list):
            raise ProviderBadResponse(PROVIDER, "GetWeeklyTopSellers: missing ranks")
        out: list[ChartEntry] = []
        for i, r in enumerate(ranks):
            if not isinstance(r, dict):
                continue
            appid = r.get("appid") or (r.get("item") or {}).get("id")
            if isinstance(appid, int):
                out.append(ChartEntry(appid, int(r.get("rank") or i + 1), None))
        return out

    def current_players(self, appid: int) -> int | None:
        """Concurrent players right now (ISteamUserStats/GetNumberOfCurrentPlayers).

        Returns None when Steam has no count for the app (result != 1)."""
        data = self._http.get_json(
            f"{self._base}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", {"appid": appid}
        )
        response = (data or {}).get("response")
        if not isinstance(response, dict):
            raise ProviderBadResponse(PROVIDER, "GetNumberOfCurrentPlayers: missing response")
        if response.get("result") != 1:
            return None
        return _int_or_none(response.get("player_count"))

    def get_tag_list(self) -> dict[int, str]:
        data = self._http.get_json(
            f"{self._base}/IStoreService/GetTagList/v1/", {"language": self._language}
        )
        tags = (data or {}).get("response", {}).get("tags")
        if not isinstance(tags, list):
            raise ProviderBadResponse(PROVIDER, "GetTagList: missing tags")
        return {int(t["tagid"]): str(t["name"]) for t in tags if "tagid" in t and "name" in t}

    def get_player_categories(self) -> dict[int, str]:
        """Player-support categories (single-player, co-op, PvP, ...)."""
        data = self._http.get_json(
            f"{self._base}/IStoreBrowseService/GetStoreCategories/v1/",
            {"input_json": json.dumps({"language": self._language})},
        )
        cats = (data or {}).get("response", {}).get("categories")
        if not isinstance(cats, list):
            raise ProviderBadResponse(PROVIDER, "GetStoreCategories: missing categories")
        return {
            int(c["categoryid"]): str(c["display_name"])
            for c in cats
            if c.get("type") == 1 and "categoryid" in c and "display_name" in c
        }
