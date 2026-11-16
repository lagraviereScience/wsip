"""Steam sign-in routes. The browser is redirected here by full-page navigation."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import AppSettings, CurrentUser, DbSession, auth_throttle, session_token
from app.core.config import Settings
from app.core.security import hash_token
from app.database.redis import get_redis
from app.integrations import factory
from app.integrations.http import ProviderHttpClient
from app.integrations.steam.openid import OpenIDError, SteamOpenIDVerifier
from app.repositories import users as users_repo
from app.services import auth as auth_service
from app.services.auth import STATE_COOKIE, RedisNonceStore
from app.workers.tasks import import_library

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_SIGNIN_ERROR_PATH = "/signin/error"


def _verifier(settings: Settings) -> SteamOpenIDVerifier:
    http = ProviderHttpClient(
        "steam_openid", throttle=None, timeout_s=settings.http_timeout_s, max_retries=1
    )
    return SteamOpenIDVerifier(
        http, RedisNonceStore(get_redis()), op_endpoint=settings.steam_openid_endpoint
    )


@router.get("/steam/login", dependencies=[Depends(auth_throttle)])
def steam_login(
    settings: AppSettings,
    next: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    start = auth_service.begin_login(get_redis(), settings, next)
    response = RedirectResponse(start.redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    # Lax: the cookie must accompany Steam's top-level GET redirect back to us.
    response.set_cookie(
        STATE_COOKIE,
        start.state,
        max_age=int(auth_service.STATE_TTL.total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/api/auth/steam",
    )
    return response


@router.get("/steam/callback", dependencies=[Depends(auth_throttle)])
def steam_callback(request: Request, db: DbSession, settings: AppSettings) -> RedirectResponse:
    params = {k: v for k, v in request.query_params.items() if len(v) <= 2048}
    try:
        result = auth_service.complete_login(
            db,
            get_redis(),
            _verifier(settings),
            factory.steam_profile_source(settings),
            settings,
            params,
            request.cookies.get(STATE_COOKIE),
        )
    except OpenIDError as exc:
        db.rollback()
        logger.warning("steam sign-in rejected", extra={"reason": exc.code})
        response = RedirectResponse(
            f"{_SIGNIN_ERROR_PATH}?reason={exc.code}", status_code=status.HTTP_303_SEE_OTHER
        )
        response.delete_cookie(STATE_COOKIE, path="/api/auth/steam")
        return response

    if result.sync_run_id is not None:
        import_library.delay(result.sync_run_id)
    logger.info(
        "steam sign-in", extra={"user_id": str(result.user_id), "new_user": result.is_new_user}
    )
    response = RedirectResponse(result.next_path, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/steam")
    response.set_cookie(
        settings.session_cookie_name,
        result.session_token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbSession, settings: AppSettings) -> Response:
    auth_service.logout(db, session_token(request, settings))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


class SessionOut(BaseModel):
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    current: bool


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    request: Request, db: DbSession, user: CurrentUser, settings: AppSettings
) -> list[SessionOut]:
    """The signed-in user's active sessions (no tokens or hashes are exposed)."""
    token = session_token(request, settings)
    current = hash_token(token) if token else b""
    return [
        SessionOut(
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            current=s.token_hash == current,
        )
        for s in users_repo.sessions_for_user(db, user.id)
    ]


@router.post("/logout-others", status_code=status.HTTP_200_OK)
def logout_others(
    request: Request, db: DbSession, user: CurrentUser, settings: AppSettings
) -> dict[str, int]:
    """Sign out every other device; this session stays signed in."""
    token = session_token(request, settings)
    revoked = users_repo.revoke_user_sessions(
        db, user.id, except_hash=hash_token(token) if token else None
    )
    db.commit()
    return {"revoked": revoked}
