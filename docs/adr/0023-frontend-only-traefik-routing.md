# ADR-0023: Traefik routes to the frontend only; the frontend forwards `/api/*`

- Status: Accepted · Date: 2026-11-16 · Records the deployed `docker-compose.yml` · Amends [ADR-0002](0002-same-origin-api-routing.md) and [ADR-0021](0021-single-production-compose-file.md)

## Context
ADR-0002 and ADR-0021 had Traefik route `Host && PathPrefix(/api)` straight to the
backend, with both `backend` and `frontend` on the external Traefik network and the
labels driven by `.env` (`PUBLIC_HOSTNAME`, `TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT`,
`TRAEFIK_CERT_RESOLVER`). That layout also added a `wdywtp-headers` middleware for HSTS.

The deployed server shares its Traefik network with other Compose stacks. Generic
service names such as `postgres`, `redis` or `backend` then resolve to several
containers on that network.

## Decision
1. **Only `frontend` joins the Traefik network and carries Traefik labels.** It serves
   the whole site, and its Next.js rewrite forwards `/api/*` to the backend over the
   project's `edge` network. The rewrite target is compiled into the frontend image at
   build time (`BACKEND_INTERNAL_URL`, default `http://wdywtp-backend:8000`). Server-side
   rendering calls the same address at run time.
2. **The backend is not on the Traefik network.** It is on `internal` and `edge` only,
   so it has no route from outside except through the frontend.
3. **Unique network aliases**: `wdywtp-backend` (on `edge`), `wdywtp-postgres` and
   `wdywtp-redis` (on `internal`). `DB_HOST`, `REDIS_HOST` and `BACKEND_INTERNAL_URL`
   use them, so name resolution never reaches another stack's container.
4. **The Traefik labels in `docker-compose.yml` are literal values** for this server: the
   host rule, the `websecure` entrypoint, the certificate resolver name and the external
   network name. They are not read from `.env`. Another server edits those lines.

## Consequences
- The browser still sees one origin (ADR-0002's goal): cookies stay first-party and no
  CORS is needed.
- Every API request now makes one extra hop through the Next.js server. The Stage 6
  load test ran on the earlier layout and does not measure this.
- `PUBLIC_HOSTNAME`, `TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT` and `TRAEFIK_CERT_RESOLVER`
  in `.env` are no longer used by `docker-compose.yml`. `scripts/check-env.sh` still
  requires `PUBLIC_HOSTNAME`, `TRAEFIK_NETWORK` and `TRAEFIK_CERT_RESOLVER`, so they must
  stay filled in for that diagnostic to pass.
- **HSTS is no longer set by this application.** The `wdywtp-headers` middleware is gone,
  and neither the backend nor `next.config.ts` sends `Strict-Transport-Security`. It must
  come from the server's Traefik configuration, or the middleware must be added back.
- **Client IPs:** the backend's direct peer is now the frontend container, not Traefik.
  uvicorn trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`, so that value must
  cover the `edge` network (and Traefik's address, which is the next hop in the chain).
  Otherwise every visitor shares the frontend's IP for the per-IP rate limits, including
  the sign-in throttle (20/min). Whether Next.js's rewrite proxy passes `X-Forwarded-For`
  through has not been verified on this layout.
- The comment in `frontend/next.config.ts` that calls the rewrite "only a fallback"
  predates this decision: the rewrite is now the production path.
