# ADR-0002: Same-origin API routing

- Status: Accepted · Date: 2026-11-14

## Context
Steam OpenID login will establish a session cookie that must be `HttpOnly`, `Secure` and `SameSite`. Cross-origin API calls would need CORS with credentials and weaken the cookie policy.

## Decision
The browser sees one origin. `/api/*` is the backend and everything else is the frontend.
- Production: Traefik routes `Host && PathPrefix(/api)` to the backend with higher priority than the frontend router.
- Local Compose: a Next.js rewrite forwards `/api/*` to `http://backend:8000`. The target is fixed at build time through `BACKEND_INTERNAL_URL` because rewrites are compiled into the standalone build.
- Server-side rendering will call the backend over the internal network (`http://backend:8000`), forwarding the session cookie.

## Consequences
- No CORS configuration and first-party cookies only.
- The `/api` prefix is reserved. Frontend route handlers must not use it (the frontend health check is `/healthz`).
