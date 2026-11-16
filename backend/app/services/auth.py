"""Steam sign-in orchestration: login start, callback verification, sessions.

State/CSRF: OpenID 2.0 has no state parameter, so each login attempt gets a
random single-use state that (a) is stored server-side in Redis with the
post-login destination, (b) travels inside ``return_to``, and (c) is bound to an
HttpOnly cookie. The callback requires all three to match.

Account linking: a SteamID64 maps to exactly one user. Signing in with another
Steam account always yields a different user and a fresh session; accounts are
never linked implicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_token, new_token, safe_next_path
from app.integrations.http import ProviderError
from app.integrations.platform import PlatformProfile, ProfileSource
from app.integrations.steam.openid import OpenIDError, SteamOpenIDVerifier, build_login_url
from app.integrations.steam.web_api import SteamAccountNotFound, SteamApiKeyMissing
from app.repositories import library as library_repo
from app.repositories import users as users_repo

STATE_TTL = timedelta(minutes=10)
STATE_COOKIE = "wdywtp_oid_state"
CALLBACK_PATH = "/api/auth/steam/callback"
# Re-import on login only if the last sync is older than this.
LOGIN_SYNC_MIN_AGE = timedelta(hours=1)


class RedisNonceStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def claim(self, nonce: str, ttl: timedelta) -> bool:
        key = "oid:nonce:" + hashlib.sha256(nonce.encode()).hexdigest()
        return bool(self._redis.set(key, "1", nx=True, ex=int(ttl.total_seconds())))


@dataclass(frozen=True, slots=True)
class LoginStart:
    redirect_url: str
    state: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    session_token: str
    next_path: str
    user_id: uuid.UUID
    is_new_user: bool
    sync_run_id: int | None


def callback_url(settings: Settings, state: str) -> str:
    return f"{settings.public_base_url}{CALLBACK_PATH}?{urlencode({'state': state})}"


def begin_login(redis: Redis, settings: Settings, next_path: str | None) -> LoginStart:
    state = new_token(24)
    redis.set(f"oid:state:{state}", safe_next_path(next_path), ex=int(STATE_TTL.total_seconds()))
    url = build_login_url(
        op_endpoint=settings.steam_openid_endpoint,
        return_to=callback_url(settings, state),
        realm=settings.public_base_url,
    )
    return LoginStart(redirect_url=url, state=state)


def complete_login(
    db: Session,
    redis: Redis,
    verifier: SteamOpenIDVerifier,
    profiles: ProfileSource | None,
    settings: Settings,
    params: Mapping[str, str],
    state_cookie: str | None,
) -> LoginResult:
    state = params.get("state", "")
    if not state or not state_cookie or not hmac.compare_digest(state, state_cookie):
        raise OpenIDError("state_mismatch")
    next_path = redis.getdel(f"oid:state:{state}")  # single use
    if next_path is None:
        raise OpenIDError("state_expired")

    steamid = verifier.verify(params, expected_return_to=callback_url(settings, state))

    profile: PlatformProfile | None = None
    if profiles is not None:
        try:
            profile = profiles.get_profile(steamid)
        except (ProviderError, SteamApiKeyMissing, SteamAccountNotFound):
            profile = None  # best effort: sign-in never depends on profile lookup

    user, link, created = users_repo.get_or_create_platform_user(db, "steam", steamid, profile)
    now = datetime.now(UTC)
    user.last_login_at = now
    token = new_token()
    users_repo.create_session(
        db, user.id, hash_token(token), timedelta(days=settings.session_ttl_days)
    )

    run_id: int | None = None
    # Automatic import only exists in steam_import mode (ADR-0014).
    if settings.library_mode == "steam_import" and (
        link.last_synced_at is None or now - link.last_synced_at > LOGIN_SYNC_MIN_AGE
    ):
        run, is_new_run = library_repo.enqueue_sync_run(db, user.id, "steam", "login")
        run_id = run.id if is_new_run else None
    db.commit()
    return LoginResult(token, str(next_path), user.id, created, run_id)


def logout(db: Session, token: str | None) -> None:
    if token:
        users_repo.revoke_session(db, hash_token(token))
        db.commit()
