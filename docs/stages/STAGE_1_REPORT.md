# Stage 1 report: foundation, architecture and infrastructure

Prompt: [docs/spec/prompts/PROMPT_1_FOUNDATION.md](../spec/prompts/PROMPT_1_FOUNDATION.md) · Date: 2026-11-14

## Environment inspection

| Item | Finding |
|---|---|
| Repository | Empty directory, not a git repository. Initialised a repository (`main`). No existing code, Docker config or infrastructure to preserve. |
| Dev machine | WSL2 (Ubuntu), 24 cores, 31 GB RAM. Node 20.18, Python 3.10 (3.12 installed via uv). |
| Docker | Docker Desktop 29.8.2 with Compose v5.5.1 through WSL integration (enabled by the owner during this stage). One unrelated project network (`portfolio-website_portfolio-network`) exists on the engine and is left untouched. This stack uses its own `wdywtp_*` networks and volumes. |
| Database infrastructure | None present locally. PostgreSQL and Redis are provided by this stack. |
| Deployment conventions | The production server is a different machine. Its Traefik network, resolver and hostname are unknown and parametrised (OPEN_QUESTIONS #14). |

## Delivered

- Repository structure per spec §6 ([ADR-0001](../adr/0001-modular-monolith.md)).
- **Backend**: FastAPI app factory, typed settings that refuse placeholder secrets in production, JSON logging with request IDs, security headers, `/api/health/live` and `/api/health/ready` (database, Redis, schema-at-head), sync SQLAlchemy engine/session, Redis client, Alembic with baseline revision `0001`.
- **Frontend**: responsive Next.js 16 app with a "night arcade" visual identity, local component library, landing page and the seven spec §30 pages. All data is fictional mock data behind a data layer and labelled with a preview banner. `/healthz` health route, `/api` rewrite to the backend.
- **Infrastructure**: `compose.yaml` (postgres, redis, one-shot migrate, backend, frontend, `backend-tests` profile), internal-only network for data services, least-privilege DB roles, hardened containers, resource limits, log rotation, health checks, restart policies. `compose.traefik.yaml` production overlay.
- **Scripts**: `init-env.sh` (generated secrets), `smoke-test.sh`, `verify-persistence.sh`, `backup-db.sh`.
- **Docs**: README, ARCHITECTURE, DATABASE, DEPLOYMENT, `.env.example`, ADR-0001…0009, master spec and open questions.

## Verification

| Check | Result |
|---|---|
| Backend unit tests (`uv run pytest`) | 13 passed (5 integration tests skipped without services) |
| Backend lint/format/types (`ruff`, `mypy --strict`) | clean |
| Frontend tests (`npm test`) | 16 passed |
| Frontend lint and typecheck | clean. The mock-import lint rule was confirmed to fire. |
| Frontend production build | succeeds. Pages prerender; `/healthz` is dynamic. |
| Frontend standalone server + backend (no Docker) | all 8 pages 200, unknown page 404, `/healthz` ok, `/api` proxy ok, readiness 503 as expected without DB |
| Visual review | desktop (1440 px) and narrow (500 px) screenshots reviewed. The preference bar layout and the logo gradient were fixed after review. |
| `docker compose up -d --build --wait` | all services healthy, `migrate` exited 0 (`Running upgrade -> 0001`) |
| `scripts/smoke-test.sh` | **23/23 passed** (before and after a full restart) |
| `docker compose --profile test run --rm backend-tests` | **18/18 passed**, including 5 integration tests: UTC sessions, Redis round trip, runtime role denied DDL, migration downgrade→upgrade, live readiness |
| `scripts/verify-persistence.sh` | probe row survived `docker compose down` + `up` |
| `scripts/backup-db.sh` | dump written (mode 600) and readable by `pg_restore --list` |
| Container hardening | backend/frontend/migrate run as non-root (uid 10001 / `node`), read-only root FS, `cap_drop: ALL`, `no-new-privileges`, memory limits applied |
| Secret exposure | Redis password value absent from process arguments; Traefik overlay refuses to render without its required variables |

One defect was found and fixed during the Docker run: the config unit tests read
the container's real `DB_*` variables. `tests/unit/conftest.py` now clears
settings variables for unit tests.

### Acceptance criteria status

| Criterion | Status |
|---|---|
| Application starts through Docker Compose | ✅ `docker compose up -d --build --wait` |
| Frontend accessible | ✅ http://127.0.0.1:3000, all pages 200 |
| Backend accessible | ✅ http://127.0.0.1:8000/api/health/ready → 200 |
| PostgreSQL is persistent | ✅ `verify-persistence.sh` |
| Redis is operational | ✅ readiness check and integration round trip |
| Migrations work | ✅ `migrate` service, downgrade/upgrade round trip |
| Health checks pass | ✅ all Docker health checks healthy; readiness all `ok` |
| Automated smoke tests pass | ✅ smoke 23/23, backend 18/18, frontend 16/16 |
| No secrets committed | ✅ `.env` gitignored (mode 600), only placeholders in `.env.example`, secret scan of trackable files clean |

**Stage 1 acceptance criteria are met.** Not exercised: the Traefik overlay
against a real Traefik (production details unknown, OPEN_QUESTIONS #14) and a
backup restore (documented in DEPLOYMENT.md, not rehearsed).

## Deviations from the spec

- Tests are in `backend/tests/` rather than `backend/app/tests/` ([ADR-0001](../adr/0001-modular-monolith.md)).
- Celery is not deployed yet. It arrives with the first background job.
- Steam OpenID will use an in-house verifier ([ADR-0008](../adr/0008-steam-openid-verification.md)), and collaborative filtering will use `implicit` ([ADR-0009](../adr/0009-collaborative-filtering-library.md)). Both were approved by the product owner.

## Notes for the next stage

- The relational schema from spec §26 is not created yet. Add models under `app/models/`, import them in `app/models/__init__.py`, then autogenerate and review a migration. Follow the conventions in DATABASE.md.
- Pages consume `src/lib/data/`. Swap each loader to the REST API as endpoints land. Per-user data will make pages dynamic, so wrap them in Suspense (Cache Components).
- Security items scheduled with authentication: CSRF, rate limiting, auth throttling, sessions, dependency scanning in CI.
- Still open: OPEN_QUESTIONS #2–5, #9, #13 and #14.
