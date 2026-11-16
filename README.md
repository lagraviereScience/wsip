# What Do You Want to Play?

Personal video game recommendations from your Steam library. The app analyses a
player's library and play history, builds a gamer profile, and produces three
lists: **games you own that you should play**, **games you don't own that you
should play**, and **trending games that suit you**. The recommendations come
from specialised recommender models trained on gaming data. No general-purpose
LLM is involved.

> **Status: Stage 6 (trending data, production hardening and release).** Self-collected
> Steam player counts with freshness and reliability checks, completion times (IGDB, off
> until configured), rate limits, session management, retention, backups and restore,
> a production Compose overlay, a provider circuit breaker, and a 100-concurrent-user load
> test with zero errors ([docs/PERFORMANCE.md](docs/PERFORMANCE.md)). Documentation index:
> [docs/README.md](docs/README.md). Testing: [docs/TESTING.md](docs/TESTING.md).
> Acceptance: [docs/stages/STAGE_6_REPORT.md](docs/stages/STAGE_6_REPORT.md).
>
> Earlier: **Stage 5 (satisfaction prediction and daily model training).** A LightGBM
> satisfaction model with calibration, category rankers, a daily training pipeline with
> versioning, rollback and reports, and daily monitoring are in place
> ([docs/SATISFACTION.md](docs/SATISFACTION.md),
> [docs/stages/STAGE_5_REPORT.md](docs/stages/STAGE_5_REPORT.md)). Models deploy only once
> enough real data exists; until then ranking stays on Match.
>
> Earlier: **Stage 4 (behaviour tracking and collaborative learning).** Users sign in
> through Steam OpenID. Their library and playtime are imported automatically (operator's
> `STEAM_WEB_API_KEY`, ADR-0015), a numerical gamer profile is inferred, and the app recommends
> owned, unowned and trending games with explanations traced to actual features
> ([docs/RECOMMENDATIONS.md](docs/RECOMMENDATIONS.md)). Players can like, dislike, favourite,
> save, dismiss or rate games. Feedback adapts their profile, and every impression and action
> is logged ([docs/BEHAVIOUR.md](docs/BEHAVIOUR.md)). A daily pipeline trains collaborative
> models and deploys one only when enough real players exist and it beats the baselines
> ([docs/COLLABORATIVE.md](docs/COLLABORATIVE.md)). Privacy controls: training opt-out, export
> and account deletion ([docs/PRIVACY.md](docs/PRIVACY.md)).
> See [docs/stages/STAGE_4_REPORT.md](docs/stages/STAGE_4_REPORT.md).

> **Installing on a server? Follow [tutorial.md](tutorial.md)**: one production
> `docker-compose.yml`, behind your existing Traefik. Recommendation scoring mode:
> `AI_GRADE=TRUE|FALSE` in `.env` ([docs/SCORING_MODES.md](docs/SCORING_MODES.md)).

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, standalone build), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3 |
| Data | PostgreSQL 18 (source of truth), Redis 8 (cache, rate limits, Celery broker) |
| Jobs | Celery worker and beat scheduler (library imports, metadata ingestion) |
| Runtime | Docker Compose; Traefik in front in production |

## Deploying

On a server, after configuring `.env` ([tutorial.md](tutorial.md)):

```bash
./build.sh
docker compose up -d
```

`./build.sh` builds `wdywtp-backend:1.0`, `wdywtp-frontend:1.0` and
`wdywtp-postgres:1.0`. `docker compose up -d` runs only `docker-compose.yml`: it
creates the database on the first start, reuses it afterwards and applies
migrations automatically. Updating uses the same two commands.

## Local development (workstation)

A workstation usually has no Traefik. The test overlay `docker/dev/compose.dev.yaml`
publishes the app on localhost instead. It is never used to deploy.

1. Put the workstation values listed at the end of `.env.example` into `.env`.
2. Create the empty stand-in network once.
3. Build and start with the overlay:

```bash
docker network create wdywtp-local-proxy
./build.sh
docker compose -f docker-compose.yml -f docker/dev/compose.dev.yaml up -d --wait
./scripts/smoke-test.sh
```

Requirements: Docker Engine with Compose v2.24 or later, `openssl`, `curl`.
(Tested with Docker 29.8 / Compose v5.5 via Docker Desktop's WSL integration.)

- Frontend: <http://localhost:3000>. Use `localhost` exactly, as it must match `PUBLIC_BASE_URL` for Steam sign-in.
- Backend: <http://127.0.0.1:8000/api/health/ready> (interactive API docs at `/api/docs` outside production)

Unit and integration tests against an isolated `wdywtp_test` database and real Redis
(never touches development data):

```bash
docker compose -f docker-compose.yml -f docker/dev/compose.dev.yaml --profile test run --rm --build backend-tests
```

Check that PostgreSQL data survives a full restart:

```bash
./scripts/verify-persistence.sh
```

## Local development without Docker

Backend (uses [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
uv run pytest                 # unit tests (integration tests skip without services)
uv run ruff check . && uv run mypy app tests
uv run uvicorn app.main:app --reload    # needs DB_* / REDIS_* env vars for /ready
```

Frontend (Node ≥ 20.9):

```bash
cd frontend
npm ci
npm run dev                   # http://localhost:3000
npm test && npm run lint && npm run typecheck
```

## Repository layout

```text
backend/            FastAPI app, Alembic migrations, tests (see ARCHITECTURE.md)
frontend/           Next.js app; src/mocks holds sample data only
docker/postgres/    PostgreSQL image: first-start database and role initialisation
docker/dev/         Workstation/test overlay (localhost ports, test services)
scripts/            Backups and restore; optional .env helpers (init-env,
                    check-env); test tools (smoke, persistence, security,
                    browser checks); API doc generator
perf/               Isolated load-test stack, Locust scenarios, results
docs/spec/          Master specification and stage prompts (authoritative)
docs/adr/           Architecture decision records
docs/stages/        Per-stage hand-off reports
build.sh            Builds the three images (tag 1.0)
docker-compose.yml  The deployment: runs the images (the only Compose file needed)
tutorial.md         Installation and deployment guide
```

## Documentation

Start at the index: [docs/README.md](docs/README.md).

- [ARCHITECTURE.md](ARCHITECTURE.md): modules, runtime topology, request flow
- [DATABASE.md](DATABASE.md): roles, migrations, conventions, planned schema
- [DEPLOYMENT.md](DEPLOYMENT.md): production deployment behind Traefik, backups, recovery
- [docs/adr/](docs/adr/): architecture decisions
- [docs/PROVIDERS.md](docs/PROVIDERS.md): external data providers, terms review and status
- [docs/API.md](docs/API.md): HTTP API (generated from the OpenAPI schema)
- [docs/MACHINE_LEARNING.md](docs/MACHINE_LEARNING.md): learning methodology and evaluation reports
- [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md), [docs/BACKUP_AND_RECOVERY.md](docs/BACKUP_AND_RECOVERY.md)
- [docs/TESTING.md](docs/TESTING.md), [docs/PERFORMANCE.md](docs/PERFORMANCE.md): test and load-test results
- [docs/spec/OPEN_QUESTIONS.md](docs/spec/OPEN_QUESTIONS.md): specification gaps and working defaults

## Secrets

`.env` is gitignored and created with mode 600. Only `.env.example`, which holds
placeholders, is committed. The backend refuses to start with
`APP_ENV=production` if any secret is missing or still a placeholder.

What Do You Want to Play? is not affiliated with Valve Corporation or Steam.
