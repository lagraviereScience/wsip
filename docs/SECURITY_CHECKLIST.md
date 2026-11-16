# Security checklist

Status of every security control (spec §35, Prompt 6 C), with where it is enforced
and how it is checked. `scripts/security-check.sh` automates the checks marked 🤖.
Last full run: see [TESTING.md](TESTING.md).

> **Verification column:** the unit and integration tests it names, and
> `scripts/smoke-test.sh`, are not in this repository. Those controls were verified
> when the test suites existed; today only the 🤖 checks and code review can be re-run.
> The Traefik rows below describe ADR-0023's layout (Traefik routes to the frontend
> only), which no test has covered yet.

## Before every release

```bash
./scripts/security-check.sh
```

It checks: dependency vulnerabilities (Python and JavaScript), secrets, network
exposure, container users and file systems, and HTTP security headers. It does not
check HSTS. Run it on the deployed stack; the dependency audits need `uv` and `npm`
and are skipped on a server without them.

## Controls

| Area | Control | Where | Verified by |
|---|---|---|---|
| Authentication | Steam OpenID 2.0, verified with Steam (`check_authentication`); single-use state and nonce (replay protection); open-redirect-safe `next` | `integrations/steam/openid.py`, `services/auth.py` | Unit + integration tests |
| Authentication | Sign-in throttled per IP (20/min) | `api/deps.py` | Integration test |
| Sessions | Opaque random token in an HttpOnly, SameSite=Lax cookie (Secure on https); only a SHA-256 hash is stored | `services/auth.py`, `models/users.py` | Unit tests |
| Sessions | Absolute expiry 30 days (`SESSION_TTL_DAYS`); **idle expiry 14 days** (`SESSION_IDLE_DAYS`); logout revokes; **"sign out other devices"**; expired sessions purged daily | `repositories/users.py`, `api/routes/auth.py` | Integration test (`test_release.py`) |
| CSRF | `Origin`/`Referer` must equal `PUBLIC_BASE_URL` on POST/PUT/PATCH/DELETE | `core/middleware.py` | Unit test 🤖 (smoke) |
| Rate limiting | General: 600/min per session, 300/min per anonymous IP, 1200/min public catalogue; per action: events, feedback, search, export. Per-IP limits need `FORWARDED_ALLOW_IPS` to cover the frontend's `edge` network, or every visitor shares one IP (DEPLOYMENT.md §3) | `core/middleware.py`, routes | Unit + integration tests |
| Rate limiting | Fails **open** if Redis is down (availability first), with a 30 s circuit breaker so requests don't wait on Redis | `database/redis.py` | Unit test |
| Input validation | Pydantic models on every body and query; path parameters constrained; request bodies over 256 KiB → 413; chunked bodies without length → 411 | schemas, `core/middleware.py` | Unit tests |
| SQL injection | SQLAlchemy with bound parameters everywhere; no string-built SQL with user input | repositories | Code review; ruff S608 |
| XSS | React escapes output; API returns JSON only with `Content-Security-Policy: default-src 'none'`; no `dangerouslySetInnerHTML` | frontend, `core/middleware.py` | 🤖 headers |
| Clickjacking, sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` (both apps); `Permissions-Policy` (web app) | `next.config.ts`, middleware | 🤖 headers |
| Error handling | Unhandled errors return a generic JSON 500 with a request id; stack traces only in logs | `main.py` | Unit test |
| Secrets | `.env` mode 600, never committed, secrets generated with `openssl rand` (tutorial.md C); empty secrets stop `docker compose up`; the app refuses to start in production with placeholder secrets or a non-https URL; the Steam key never logged (httpx URL logging off) and never in a URL we log; IGDB secret sent in the request body, not the URL | `core/config.py`, `.gitignore` | 🤖 + unit tests |
| Least privilege (DB) | Runtime role has DML only; migrations use a separate owner role | `docker/postgres/provision.sh` | Integration tests run as the runtime role |
| Network exposure | PostgreSQL and Redis only on an `internal: true` network; workers and scheduler publish nothing; production publishes nothing. Traefik routes to the frontend only; the backend is reached through the frontend's `/api/*` rewrite and is not on Traefik's network (ADR-0023) | `docker-compose.yml` | 🤖 exposure check (also: database and Redis never on Traefik's network) |
| Containers | Non-root users; read-only root file systems; `no-new-privileges`; all capabilities dropped; CPU and memory limits; restart policies | `docker-compose.yml`, Dockerfiles | 🤖 |
| HTTPS | Terminated by the existing Traefik (certificate resolver named in the `frontend` labels). **No HSTS is set by the application** since ADR-0023 removed the headers middleware; set it in Traefik | `docker-compose.yml` (Traefik labels) | Routing, TLS and HSTS were verified on 2026-11-15 through a local Traefik v3.6, on the earlier two-router layout; the current layout is not verified |
| Dependencies | `pip-audit` on the locked runtime set; `npm audit` (production, high+) | `scripts/security-check.sh` | 🤖 |
| Admin surface | No admin HTTP endpoints; operations via CLI inside the worker container; API docs disabled in production | `cli.py`, `main.py` | Code review |
| Privacy | Per-user data isolation; training opt-out; pseudonymised training data; export and account deletion; retention limits | see [PRIVACY.md](PRIVACY.md) | Integration tests |
| External providers | Typed errors, bounded retries, per-provider throttles, **circuit breaker** (2 min) after an outage, no scraping | `integrations/http.py` | Unit tests |
| Logging | JSON logs with request ids; paths without query strings; no tokens, keys or emails | `core/logging.py`, middleware | Code review, secret scan |

## Known gaps (accepted for now)

- Monitoring alerts are stored and visible via `app.cli monitor` / `status`, but not
  pushed to an alerting system (OPEN_QUESTIONS #32).
- HTTPS can only be verified on the real server behind Traefik. HSTS is not set by the
  application at all since ADR-0023.
- Client-IP forwarding through the frontend's rewrite is not verified (DEPLOYMENT.md §3).
- No automated tests are in this repository (see the note at the top).
- Docker secrets (files) are not used; secrets are environment variables from a
  mode-600 `.env` readable only by root and the deploy user. Anyone with Docker
  access can read them with `docker inspect` (Docker access is root-equivalent anyway).
- Legal review items (Steam terms, training consent, privacy policy): see
  [PRIVACY.md](PRIVACY.md) "Before public launch".
