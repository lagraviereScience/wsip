"""Key-free public Steam profile lookup (sign-in-only mode, ADR-0014).

Valve serves a structured XML view of public community profiles at
``https://steamcommunity.com/profiles/<steamid64>/?xml=1``. It needs no API key
and is used only for the signed-in user's own display name, avatar and profile
visibility, never to read libraries. (The equivalent games XML feed no longer
exists; reading the HTML games page would be scraping and is not done.)

Parsed with defusedxml (no entity expansion / external entities).
"""

from __future__ import annotations

from defusedxml import DefusedXmlException, ElementTree

from app.integrations.http import ProviderBadResponse, ProviderHttpClient
from app.integrations.platform import PlatformProfile

PROVIDER = "steam_community"
_VISIBILITY_PUBLIC = 3


class SteamCommunityProfileClient:
    def __init__(
        self, http: ProviderHttpClient, base_url: str = "https://steamcommunity.com"
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")

    def get_profile(self, steamid: str) -> PlatformProfile:
        response = self._http.request(
            "GET", f"{self._base}/profiles/{steamid}/", params={"xml": "1"}
        )
        if response.status_code != 200 or "xml" not in response.headers.get("content-type", ""):
            raise ProviderBadResponse(PROVIDER, f"HTTP {response.status_code}")
        try:
            root = ElementTree.fromstring(response.content)
        except (ElementTree.ParseError, DefusedXmlException) as exc:
            raise ProviderBadResponse(PROVIDER, "invalid XML") from exc
        if root.tag != "profile" or (root.findtext("steamID64") or "").strip() != steamid:
            raise ProviderBadResponse(PROVIDER, "unexpected profile document")
        visibility_text = (root.findtext("visibilityState") or "").strip()
        visibility = int(visibility_text) if visibility_text.isdigit() else None
        name = (root.findtext("steamID") or "").strip() or "Steam player"
        avatar = (root.findtext("avatarFull") or root.findtext("avatarMedium") or "").strip()
        return PlatformProfile(
            external_user_id=steamid,
            display_name=name[:200],
            profile_url=f"{self._base}/profiles/{steamid}/",
            avatar_url=avatar if avatar.startswith("https://") else None,
            visibility=visibility,
            profile_is_public=visibility == _VISIBILITY_PUBLIC,
        )
