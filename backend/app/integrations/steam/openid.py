"""Steam OpenID 2.0 relying party (ADR-0008).

Steam is an OpenID 2.0 provider (https://partner.steamgames.com/doc/features/auth).
After a positive assertion the claimed identifier is
``https://steamcommunity.com/openid/id/<steamid64>``. A SteamID64 is extracted
ONLY after every check below has passed:

1. ``openid.mode`` is ``id_res`` (``cancel`` means the user backed out).
2. Namespace and ``op_endpoint`` are exactly Steam's.
3. ``return_to`` equals the URL we generated for this login attempt.
4. ``claimed_id`` equals ``identity`` and has Steam's exact format.
5. All security-relevant fields are covered by the signature (``openid.signed``).
6. ``response_nonce`` is recent and has never been seen before (replay protection).
7. Steam itself confirms the assertion via ``check_authentication`` (direct
   server-to-server verification; we never trust the browser-supplied data alone).

CSRF/state protection is handled by the caller (``app.services.auth``): OpenID 2.0
has no ``state`` parameter, so our own single-use state travels inside return_to
and is bound to an HttpOnly cookie.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from app.integrations.http import ProviderError, ProviderHttpClient

OPENID_NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
STEAM_OP_ENDPOINT = "https://steamcommunity.com/openid/login"
# Individual-account SteamID64s start with 7656119; Valve documents the http
# form of the claimed id while live responses use https, so accept both.
_CLAIMED_ID = re.compile(r"^https?://steamcommunity\.com/openid/id/(7656119\d{10})$")
_REQUIRED_SIGNED = frozenset(
    {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"}
)
NONCE_MAX_AGE = timedelta(minutes=5)
NONCE_MAX_FUTURE_SKEW = timedelta(minutes=1)


class OpenIDError(Exception):
    """Login failed. ``code`` is safe to show to users and to log."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class NonceStore(Protocol):
    def claim(self, nonce: str, ttl: timedelta) -> bool:
        """Record the nonce; return False if it was already used."""
        ...


def build_login_url(*, op_endpoint: str, return_to: str, realm: str) -> str:
    params = {
        "openid.ns": OPENID_NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    return f"{op_endpoint}?{urlencode(params)}"


def _parse_nonce_time(nonce: str) -> datetime:
    # OpenID 2.0 §10.1: nonce starts with a UTC timestamp, e.g. 2026-11-14T20:00:00Z
    try:
        return datetime.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise OpenIDError("invalid_response", "malformed nonce") from exc


def _parse_key_value(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            result[key.strip()] = value.strip()
    return result


class SteamOpenIDVerifier:
    def __init__(
        self,
        http: ProviderHttpClient,
        nonces: NonceStore,
        *,
        op_endpoint: str = STEAM_OP_ENDPOINT,
        now: type[datetime] = datetime,
    ) -> None:
        self._http = http
        self._nonces = nonces
        self._op_endpoint = op_endpoint
        self._now = now

    def verify(self, params: Mapping[str, str], *, expected_return_to: str) -> str:
        """Validate a callback and return the verified SteamID64."""
        mode = params.get("openid.mode")
        if mode == "cancel":
            raise OpenIDError("cancelled")
        if mode != "id_res":
            raise OpenIDError("invalid_response", "unexpected mode")
        if params.get("openid.ns") != OPENID_NS:
            raise OpenIDError("invalid_response", "namespace")
        if params.get("openid.op_endpoint") != self._op_endpoint:
            raise OpenIDError("endpoint_mismatch")
        if params.get("openid.return_to") != expected_return_to:
            raise OpenIDError("return_to_mismatch")

        claimed_id = params.get("openid.claimed_id", "")
        if claimed_id != params.get("openid.identity"):
            raise OpenIDError("identity_mismatch")
        match = _CLAIMED_ID.fullmatch(claimed_id)
        if match is None:
            raise OpenIDError("identity_mismatch", "unexpected claimed_id format")

        signed = set(params.get("openid.signed", "").split(","))
        if not signed >= _REQUIRED_SIGNED:
            raise OpenIDError("invalid_response", "required fields not signed")
        if not params.get("openid.sig") or not params.get("openid.assoc_handle"):
            raise OpenIDError("invalid_response", "missing signature")

        nonce = params.get("openid.response_nonce", "")
        issued = _parse_nonce_time(nonce)
        now = self._now.now(UTC)
        if issued < now - NONCE_MAX_AGE or issued > now + NONCE_MAX_FUTURE_SKEW:
            raise OpenIDError("nonce_expired")
        if not self._nonces.claim(nonce, NONCE_MAX_AGE + NONCE_MAX_FUTURE_SKEW):
            raise OpenIDError("nonce_replayed")

        self._check_authentication(params)
        return match.group(1)

    def _check_authentication(self, params: Mapping[str, str]) -> None:
        payload = {k: v for k, v in params.items() if k.startswith("openid.")}
        payload["openid.mode"] = "check_authentication"
        try:
            response = self._http.request("POST", self._op_endpoint, data=payload)
        except ProviderError as exc:
            raise OpenIDError("provider_unavailable", str(exc)) from exc
        if response.status_code != 200:
            raise OpenIDError("provider_unavailable", f"HTTP {response.status_code}")
        fields = _parse_key_value(response.text)
        if fields.get("ns") != OPENID_NS or fields.get("is_valid") != "true":
            raise OpenIDError("not_verified")
