"""Shared FastAPI dependencies: database session, current user, client IP, throttling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rate_limit import FixedWindowLimiter
from app.core.security import hash_token
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.models import User
from app.repositories import users as users_repo


async def get_db() -> AsyncIterator[Session]:
    """A session per request, closed on the event loop as soon as the response is done.

    It is an *async* dependency on purpose: a sync generator's clean-up would wait for
    a free threadpool thread while still holding its pooled connection, and under load
    (Stage 6 test: 100 users) requests holding connections queued behind requests
    waiting for connections until the pool timed out. Endpoints still run in the
    threadpool; closing only returns the connection to the pool."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers already resolved X-Forwarded-For from trusted proxies only.
    return request.client.host if request.client else "unknown"


def session_token(request: Request, settings: AppSettings) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


def optional_user(request: Request, db: DbSession, settings: AppSettings) -> User | None:
    token = session_token(request, settings)
    if not token or len(token) > 128:
        return None
    user = users_repo.user_for_session(
        db, hash_token(token), idle=timedelta(days=settings.session_idle_days)
    )
    # Always end the transaction: persists the throttled last_seen_at and returns the
    # connection to the pool before the endpoint runs in another threadpool step.
    db.commit()
    return user


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def auth_throttle(request: Request, settings: AppSettings) -> None:
    """Authentication throttling per client IP (spec §35)."""
    limiter = FixedWindowLimiter(get_redis(), "auth", settings.auth_rate_limit_per_minute)
    result = limiter.hit(client_ip(request))
    if not result.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Please wait a moment.",
            headers={"Retry-After": str(result.retry_after_s)},
        )
