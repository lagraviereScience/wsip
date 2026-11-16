"""Redis client shared by caching and (later) Celery coordination."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    settings = get_settings()
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password.get_secret_value() if settings.redis_password else None,
        socket_connect_timeout=settings.health_check_timeout_s,
        socket_timeout=settings.health_check_timeout_s,
        decode_responses=True,
    )


# --- Best-effort use (rate limiting, counters) --------------------------------------
# When Redis is unreachable, every call would wait for redis-py's connection retries.
# Optional features check this breaker first and skip Redis for a cool-down period.
_BREAKER_COOLDOWN_S = 30.0
_down_until = 0.0


def redis_usable() -> bool:
    import time

    return time.monotonic() >= _down_until


def mark_redis_down() -> None:
    import time

    global _down_until
    _down_until = time.monotonic() + _BREAKER_COOLDOWN_S
