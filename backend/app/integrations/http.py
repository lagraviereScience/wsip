"""Resilient outbound HTTP for provider adapters.

Every provider call goes through ``ProviderHttpClient``, which adds:
- shared cross-process throttling (``OutboundThrottle``),
- bounded retries with exponential backoff + jitter on timeouts, 429 and 5xx,
  honouring ``Retry-After``,
- typed errors so callers can tell "provider down" from "bad request".

Query strings are never logged: Steam Web API calls carry the API key there.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.rate_limit import OutboundThrottle

logger = logging.getLogger(__name__)

USER_AGENT = "WhatDoYouWantToPlay/0.2 (+game recommendation service)"


class ProviderError(RuntimeError):
    """Base class for provider failures. ``code`` is safe to persist and show."""

    code = "provider_error"

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"


class ProviderBadResponse(ProviderError):
    code = "provider_bad_response"


class ProviderAuthError(ProviderError):
    code = "provider_auth_error"


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderHttpClient:
    def __init__(
        self,
        provider: str,
        *,
        throttle: OutboundThrottle | None,
        timeout_s: float,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
        backoff_base_s: float = 1.0,
        sleep: Any = time.sleep,
        circuit_cooldown_s: float | None = None,
        redis: Any = None,
    ) -> None:
        self.provider = provider
        # Circuit breaker: after a provider stays unavailable through all retries,
        # further calls fail at once for ``circuit_cooldown_s`` instead of each
        # waiting through retries and backoff (prompt 6: remain useful when
        # providers are unavailable). Shared across processes through Redis.
        self._cooldown = circuit_cooldown_s
        self._redis = redis
        self._throttle = throttle
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=timeout_s,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def _count(self, outcome: str) -> None:
        """Hourly per-provider outcome counters in Redis (ops status, spec §36).
        Best effort: counting must never break a provider call."""
        from app.database.redis import get_redis, mark_redis_down, redis_usable

        if not redis_usable():
            return
        try:
            key = f"provider_stats:{self.provider}:{time.strftime('%Y%m%d%H', time.gmtime())}"
            pipe = get_redis().pipeline()
            pipe.hincrby(key, outcome, 1)
            pipe.expire(key, 8 * 86400)
            pipe.execute()
        except Exception:
            mark_redis_down()  # observability only: skip counting for a while

    def _circuit_key(self) -> str:
        return f"provider_down:{self.provider}"

    def _circuit_open(self) -> bool:
        if not self._cooldown:
            return False
        from app.database.redis import get_redis, mark_redis_down, redis_usable

        if self._redis is None and not redis_usable():
            return False
        try:
            return bool((self._redis or get_redis()).exists(self._circuit_key()))
        except Exception:
            mark_redis_down()
            return False

    def _trip(self) -> None:
        if not self._cooldown:
            return
        from app.database.redis import get_redis, mark_redis_down, redis_usable

        if self._redis is None and not redis_usable():
            return
        try:
            (self._redis or get_redis()).set(self._circuit_key(), "1", ex=int(self._cooldown))
            logger.warning(
                "provider circuit opened",
                extra={"provider": self.provider, "cooldown_s": self._cooldown},
            )
        except Exception:
            mark_redis_down()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        content: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if self._circuit_open():
            self._count("short_circuited")
            raise ProviderUnavailable(self.provider, "circuit open (recent outage)")
        attempt = 0
        while True:
            if self._throttle is not None:
                self._throttle.acquire()
            try:
                response = self._client.request(
                    method, url, params=params, data=data, content=content, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    self._count("unavailable")
                    self._trip()
                    raise ProviderUnavailable(self.provider, type(exc).__name__) from exc
                self._backoff(attempt, None, reason=type(exc).__name__)
                attempt += 1
                continue

            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    if response.status_code == 429:
                        self._count("rate_limited")
                        self._trip()
                        raise ProviderRateLimited(self.provider, "HTTP 429 after retries")
                    self._count("unavailable")
                    self._trip()
                    raise ProviderUnavailable(self.provider, f"HTTP {response.status_code}")
                self._backoff(
                    attempt,
                    response.headers.get("Retry-After"),
                    reason=f"HTTP {response.status_code}",
                )
                attempt += 1
                continue
            if response.status_code in (401, 403):
                self._count("auth_error")
                raise ProviderAuthError(self.provider, f"HTTP {response.status_code}")
            self._count("ok" if response.status_code < 400 else f"http_{response.status_code}")
            return response

    def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        response = self.request("GET", url, params=params)
        if response.status_code != 200:
            raise ProviderBadResponse(self.provider, f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderBadResponse(self.provider, "invalid JSON") from exc

    def _backoff(self, attempt: int, retry_after: str | None, *, reason: str) -> None:
        delay = self._backoff_base_s * (2**attempt) + random.uniform(0, self._backoff_base_s)  # noqa: S311
        if retry_after and retry_after.isdigit():
            delay = max(delay, min(float(retry_after), 60.0))
        logger.warning(
            "provider request retry",
            extra={
                "provider": self.provider,
                "attempt": attempt + 1,
                "reason": reason,
                "delay_s": round(delay, 2),
            },
        )
        self._sleep(delay)
