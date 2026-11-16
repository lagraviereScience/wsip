"""Redis-backed rate limiting.

- ``FixedWindowLimiter``: inbound throttling (e.g. authentication endpoints per IP).
- ``OutboundThrottle``: shared, cross-process pacing of calls to external
  providers so every worker together stays within the provider's limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis import Redis

# Atomically reserve the next send slot: returns how long the caller must wait (ms).
_RESERVE_SLOT = """
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local next_slot = tonumber(redis.call('GET', KEYS[1]) or '0')
local slot = math.max(now, next_slot)
redis.call('SET', KEYS[1], slot + interval, 'PX', interval * 10 + 60000)
return slot - now
"""


@dataclass(frozen=True, slots=True)
class LimitResult:
    allowed: bool
    retry_after_s: int


class FixedWindowLimiter:
    def __init__(self, redis: Redis, namespace: str, limit: int, window_s: int = 60) -> None:
        self._redis = redis
        self._namespace = namespace
        self._limit = limit
        self._window_s = window_s

    def hit(self, key: str) -> LimitResult:
        window = int(time.time() // self._window_s)
        redis_key = f"ratelimit:{self._namespace}:{key}:{window}"
        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, self._window_s + 5)
        count = int(pipe.execute()[0])
        if count > self._limit:
            retry = self._window_s - int(time.time() % self._window_s)
            return LimitResult(allowed=False, retry_after_s=max(retry, 1))
        return LimitResult(allowed=True, retry_after_s=0)


class OutboundThrottle:
    """Spaces calls to one provider evenly: at most ``per_minute`` across all processes."""

    def __init__(
        self, redis: Redis, provider: str, per_minute: int, max_wait_s: float = 120
    ) -> None:
        self._redis = redis
        self._key = f"throttle:{provider}"
        self._interval_ms = max(1, int(60_000 / per_minute))
        self._max_wait_s = max_wait_s
        self._script = redis.register_script(_RESERVE_SLOT)

    def acquire(self) -> None:
        now_ms = int(time.time() * 1000)
        wait_ms = int(self._script(keys=[self._key], args=[now_ms, self._interval_ms]))
        if wait_ms / 1000 > self._max_wait_s:
            raise ThrottleTimeout(f"{self._key}: queue wait {wait_ms} ms exceeds limit")
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)


class ThrottleTimeout(RuntimeError):
    pass
