"""Builds provider clients from settings (one place to wire throttles and keys)."""

from __future__ import annotations

from app.core.config import Settings
from app.core.rate_limit import OutboundThrottle
from app.database.redis import get_redis
from app.integrations.game_metadata.igdb import IgdbClient
from app.integrations.http import ProviderHttpClient
from app.integrations.steam.community import SteamCommunityProfileClient
from app.integrations.steam.store import SteamStoreClient
from app.integrations.steam.web_api import SteamPlatformAdapter, SteamWebApiClient


def steam_platform_adapter(settings: Settings) -> SteamPlatformAdapter:
    http = ProviderHttpClient(
        "steam_web_api",
        throttle=OutboundThrottle(
            get_redis(), "steam_web_api", settings.steam_web_api_max_calls_per_minute
        ),
        timeout_s=settings.http_timeout_s,
        max_retries=settings.http_max_retries,
        circuit_cooldown_s=settings.provider_circuit_cooldown_s,
    )
    key = settings.steam_web_api_key.get_secret_value() if settings.steam_web_api_key else None
    return SteamPlatformAdapter(
        SteamWebApiClient(http, api_key=key, base_url=settings.steam_api_base_url)
    )


def steam_profile_source(settings: Settings) -> SteamPlatformAdapter | SteamCommunityProfileClient:
    """Web API when a key exists, otherwise the key-free public profile XML."""
    if settings.steam_web_api_key is not None:
        return steam_platform_adapter(settings)
    http = ProviderHttpClient(
        "steam_community",
        throttle=OutboundThrottle(get_redis(), "steam_community", 30),
        timeout_s=settings.http_timeout_s,
        max_retries=1,
    )
    return SteamCommunityProfileClient(http)


def steam_store_client(settings: Settings) -> SteamStoreClient:
    http = ProviderHttpClient(
        "steam_store",
        throttle=OutboundThrottle(
            get_redis(), "steam_store", settings.steam_store_max_calls_per_minute
        ),
        timeout_s=settings.http_timeout_s,
        max_retries=settings.http_max_retries,
        circuit_cooldown_s=settings.provider_circuit_cooldown_s,
    )
    return SteamStoreClient(
        http,
        base_url=settings.steam_api_base_url,
        asset_base_url=settings.steam_store_asset_base_url,
        country=settings.steam_store_country,
    )


def steam_players_client(settings: Settings) -> SteamStoreClient:
    """Store client with its own throttle, for high-volume player-count sampling."""
    http = ProviderHttpClient(
        "steam_players",
        throttle=OutboundThrottle(
            get_redis(), "steam_players", settings.steam_players_max_calls_per_minute
        ),
        timeout_s=settings.http_timeout_s,
        max_retries=1,
        circuit_cooldown_s=settings.provider_circuit_cooldown_s,
    )
    return SteamStoreClient(
        http,
        base_url=settings.steam_api_base_url,
        asset_base_url=settings.steam_store_asset_base_url,
        country=settings.steam_store_country,
    )


def igdb_client(settings: Settings) -> IgdbClient | None:
    """The IGDB client, or None unless it is enabled and has credentials."""
    secret = settings.igdb_client_secret.get_secret_value() if settings.igdb_client_secret else ""
    if not (settings.igdb_enabled and settings.igdb_client_id and secret):
        return None
    http = ProviderHttpClient(
        "igdb",
        throttle=OutboundThrottle(get_redis(), "igdb", settings.igdb_max_calls_per_minute),
        timeout_s=settings.http_timeout_s,
        max_retries=settings.http_max_retries,
        circuit_cooldown_s=settings.provider_circuit_cooldown_s,
    )
    return IgdbClient(http, settings.igdb_client_id, secret)
