"""Registry of external data providers and their legal/operational status (spec §9).

Every provider is optional. A disabled provider is still listed, with the reason,
so the limitation is visible in the API (`GET /api/catalogue/providers`) and docs.
Enabling one requires its terms to be verified first (DEPLOYMENT.md, PROVIDERS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import Settings


class ProviderStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    purpose: str
    status: ProviderStatus
    reason: str


def provider_registry(settings: Settings) -> tuple[ProviderInfo, ...]:
    steam_key = settings.steam_web_api_key is not None
    return (
        ProviderInfo(
            "steam_web_api",
            "User libraries, playtime, achievements",
            ProviderStatus.ENABLED if steam_key else ProviderStatus.DISABLED,
            "Official Steam Web API (Steam Web API Terms of Use)."
            if steam_key
            else "Sign-in-only mode (ADR-0014): no key configured; users add and rate games.",
        ),
        ProviderInfo(
            "steam_community",
            "Signed-in user's public name and avatar (no key)",
            ProviderStatus.ENABLED,
            "Valve's public profile XML for the user's own profile only; never libraries.",
        ),
        ProviderInfo(
            "steam_store",
            "Game search, metadata, user tags, categories, review summaries",
            ProviderStatus.ENABLED,
            "Valve's public store API (IStoreBrowseService/IStoreService); no scraping.",
        ),
        ProviderInfo(
            "igdb",
            "Completion times (time to beat), looked up by Steam appid",
            ProviderStatus.ENABLED
            if settings.igdb_enabled and settings.igdb_client_id and settings.igdb_client_secret
            else ProviderStatus.DISABLED,
            "Free for non-commercial use under the Twitch Developer Services Agreement; "
            "commercial use requires a partnership (partner@igdb.com). Needs written "
            "confirmation for this public website and Twitch client credentials.",
        ),
        ProviderInfo(
            "rawg",
            "Additional metadata",
            ProviderStatus.DISABLED,
            "Not evaluated yet: requires API key, attribution and plan review.",
        ),
        ProviderInfo(
            "opencritic",
            "Review information",
            ProviderStatus.DISABLED,
            "Paid API access only.",
        ),
        ProviderInfo(
            "howlongtobeat",
            "Estimated game duration",
            ProviderStatus.DISABLED,
            "No public API; scraping is not authorised.",
        ),
        ProviderInfo(
            "steamdb",
            "Historical statistics",
            ProviderStatus.DISABLED,
            "No authorised data-access method; scraping prohibited.",
        ),
        ProviderInfo(
            "steamcharts",
            "Player-count trends",
            ProviderStatus.DISABLED,
            "No authorised API; trends will use self-collected player counts.",
        ),
    )
