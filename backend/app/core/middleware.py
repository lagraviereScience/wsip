"""HTTP middleware: request IDs, access logging, security headers, CSRF origin check,
request-size limit and the general API rate limit.

All of them are plain ASGI middleware. Starlette's ``BaseHTTPMiddleware`` was used
before Stage 6, but each layer adds tasks and memory streams to every request; with
four layers that cost about 6 ms of CPU per request and capped API throughput in the
100-user load test (docs/PERFORMANCE.md). Behaviour is unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

# Accept a caller-supplied ID only if it is short and harmless to echo/log.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The API returns JSON only; nothing it serves should ever load sub-resources.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    await JSONResponse({"detail": detail}, status_code=status, headers=headers)(
        scope, receive, send
    )


class RequestContextMiddleware:
    """Request id (echoed and logged), one access-log line, baseline security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id  # for the error handler
        start = time.perf_counter()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for header, value in _SECURITY_HEADERS.items():
                    if header not in headers:
                        headers[header] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            # Path only — never the query string, which may carry tokens (e.g. OpenID).
            path = scope["path"]
            if not path.startswith("/api/health/"):
                logger.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    },
                )
            request_id_var.reset(token)


class OriginCheckMiddleware:
    """CSRF defence for state-changing API requests (spec §35).

    Together with SameSite=Lax session cookies: an unsafe request must carry an
    Origin (or, failing that, Referer) header from our own public origin.
    """

    def __init__(self, app: ASGIApp, *, allowed_origin: str) -> None:
        self.app = app
        self._allowed = allowed_origin.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in _UNSAFE_METHODS
            and scope["path"].startswith("/api/")
        ):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin is None:
                referer = headers.get("referer", "")
                origin = "/".join(referer.split("/")[:3]) if referer else None
            if origin != self._allowed:
                await _reject(scope, receive, send, 403, "Cross-origin request rejected")
                return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject request bodies above a limit before the app reads them (413)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            length = headers.get("content-length")
            if length is not None:
                if not length.isdigit():
                    await _reject(scope, receive, send, 400, "Invalid Content-Length")
                    return
                if int(length) > self._max:
                    await _reject(scope, receive, send, 413, "Request body too large")
                    return
            elif scope["method"] in _UNSAFE_METHODS and "chunked" in headers.get(
                "transfer-encoding", ""
            ):
                await _reject(scope, receive, send, 411, "Content-Length required")
                return
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """General API rate limit (spec §35), in addition to the per-action limits.

    Signed-in requests are counted per session (so the frontend's server-side calls,
    which all come from one container, are counted per visitor), anonymous ones per
    client IP (as resolved by uvicorn from trusted proxies only). Public catalogue
    reads get a higher allowance. Health checks are exempt. If Redis is down the
    limit fails open: availability over strictness, logged as a warning.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        cookie_name: str,
        per_session: int,
        per_ip: int,
        per_ip_public: int,
    ) -> None:
        self.app = app
        self._cookie = cookie_name
        self._limits = {"session": per_session, "ip": per_ip, "public": per_ip_public}

    def _bucket(self, scope: Scope) -> tuple[str, str, int]:
        cookies = cookie_parser(Headers(scope=scope).get("cookie", ""))
        token = cookies.get(self._cookie)
        if token and len(token) <= 128:
            key = hashlib.sha256(token.encode()).hexdigest()[:24]
            return "session", key, self._limits["session"]
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if scope["method"] == "GET" and scope["path"].startswith("/api/catalogue/"):
            return "public", ip, self._limits["public"]
        return "ip", ip, self._limits["ip"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path.startswith("/api/health/") or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        kind, key, limit = self._bucket(scope)
        from app.core.rate_limit import FixedWindowLimiter
        from app.database.redis import get_redis, mark_redis_down, redis_usable

        if limit <= 0 or not redis_usable():
            await self.app(scope, receive, send)
            return
        try:
            result = FixedWindowLimiter(get_redis(), f"api-{kind}", limit).hit(key)
        except Exception:
            # Fail open: availability over strictness while Redis is down.
            mark_redis_down()
            logger.warning("rate limiter unavailable; allowing requests", extra={"path": path})
            await self.app(scope, receive, send)
            return
        if not result.allowed:
            await _reject(
                scope,
                receive,
                send,
                429,
                "Too many requests. Please slow down.",
                {"Retry-After": str(result.retry_after_s)},
            )
            return
        await self.app(scope, receive, send)
