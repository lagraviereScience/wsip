# Architecture

Status: Stage 2 (Steam sign-in, library import, catalogue and taxonomy). This document describes what exists now and the
module boundaries later stages build into. The authoritative requirements are in
[docs/spec/MASTER_SPECIFICATION.md](docs/spec/MASTER_SPECIFICATION.md).

## 1. Style

A **modular monolith** ([ADR-0001](docs/adr/0001-modular-monolith.md)): one
backend codebase and image, with strict internal module boundaries so that
heavy parts (training, ingestion) can later run as separate processes or
services without a rewrite. No Kubernetes, no microservices.

## 2. Runtime topology

```text
                       Internet (HTTPS)
                              │
                     ┌────────▼────────┐  production (labels in docker-compose.yml)
                     │     Traefik     │
                     └───┬─────────┬───┘
            Host(...)    │         │  Host(...) && PathPrefix(/api)
                ┌────────▼───┐ ┌───▼──────────┐
   edge network │  frontend  │ │   backend    │ uvicorn, N workers
                │  Next.js   │─┤   FastAPI    │
                └────────────┘ └──┬────────┬──┘
                   /api rewrite    │        │
                   (local only)    │        │
               ┌───────────────────▼─┐   ┌──▼──────────┐
 internal net  │  PostgreSQL 18      │   │  Redis 8    │   no outbound route,
 (internal:    │  source of truth    │   │  cache /    │   never published
  true)        └─────────▲───────────┘   │  broker     │
                         │               └─────────────┘
                ┌────────┴────────┐       ┌─────────────────────────────┐
                │ migrate (1-shot) │       │ worker (Celery, 2 procs)    │──► Steam Web API
                │ alembic + taxonomy│       │ queues: imports, catalogue, │──► Steam Store API
                └─────────────────┘       │ default   (internal + edge) │
                                          └─────────────▲───────────────┘
                                          ┌─────────────┴───────────────┐
                                          │ scheduler (Celery beat, ×1) │
                                          └─────────────────────────────┘
```

- **Same-origin API** ([ADR-0002](docs/adr/0002-same-origin-api-routing.md)):
  the browser only ever talks to one origin. `/api/*` goes to the backend
  (through Traefik in production, through a Next.js rewrite locally). This keeps
  session cookies first-party (`SameSite`, `HttpOnly`) and removes the need for CORS.
- **Start-up order**: postgres healthy → `migrate` completes → backend healthy →
  frontend. A schema migration failure stops the rollout before new code serves traffic.
- **Resource limits** are set per container so the stack cannot monopolise the
  shared server (spec §7). BLAS/OpenMP thread counts are pinned to 1 in the
  backend image; ML workers will raise them explicitly and in a controlled way.

The worker and the scheduler reuse the backend image ([ADR-0011](docs/adr/0011-background-jobs.md)).
Job state that users see lives in PostgreSQL (`library_sync_runs`). Redis is only the broker.

## 3. Backend modules

```text
backend/app/
  main.py                 app factory: logging, middleware, routers
  core/                   config (pydantic-settings), JSON logging, middleware
  api/                    routers only, thin, no SQL
    routes/health.py      /api/health/live, /api/health/ready
  schemas/                Pydantic API contracts
  services/               orchestration (health checks now)
  repositories/           all SQL lives here (from Stage 2)
  models/                 SQLAlchemy ORM models (from Stage 2)
  database/               engine/session, Redis client, Base, Alembic migrations
  integrations/           platform/provider adapters: steam/, game_metadata/, trends/
  recommendations/        features/, profiling/, candidate_generation/, ranking/, evaluation/
  machine_learning/       datasets/, training/, models/, registry/
  workers/                Celery tasks and schedules
backend/tests/            unit/ (no services), integration/ (live Postgres + Redis)
```

Dependency rule: `api → services → (repositories | integrations | recommendations)
→ models/database`. Nothing imports from `api`. `recommendations` and
`machine_learning` consume platform-independent internal data only. They never
call Steam directly (spec §29).

### Configuration

`app/core/config.py` reads every setting from environment variables. Secrets are
`SecretStr`. Database URLs are built from separate parts, so passwords never need
URL-encoding. In production the app refuses to start with missing or placeholder
secrets.

### Logging

One JSON object per line on stdout (`LOG_FORMAT=json`), so Docker's log driver
and any centralised collector can parse it. Each request is logged with method,
path (never the query string, which may carry OpenID tokens), status, duration
and a request ID. The ID is echoed in `X-Request-ID` and attached to every log
line written during the request. Health probes are not access-logged.

### Health endpoints

| Endpoint | Checks | Used by |
|---|---|---|
| `GET /api/health/live` | process only | Docker `HEALTHCHECK` (so a database outage doesn't trigger restart loops) |
| `GET /api/health/ready` | PostgreSQL `SELECT 1`, Redis `PING`, schema version = code's Alembic head | smoke tests, monitoring, Traefik if desired; returns 503 when any check fails |
| `GET /healthz` (frontend) | Next.js process | frontend Docker `HEALTHCHECK` |

Readiness responses report only `ok`/`fail` and latency for each component.
Error details go to the logs and never to the public response.

## 4. Stage 2 flows

> **Library mode.** With the operator's `STEAM_WEB_API_KEY` set (the product path,
> [ADR-0015](docs/adr/0015-automatic-steam-import-primary.md)) the import flow below runs after
> every sign-in. Without a key the app falls back to **sign-in-only mode**
> ([ADR-0014](docs/adr/0014-sign-in-only-mode.md)), where users add and rate games by hand.

### Steam sign-in (ADR-0008, ADR-0010)

```text
browser ── GET /api/auth/steam/login?next=/library ──► backend
   ◄── 303 to steamcommunity.com/openid/login + HttpOnly state cookie
       (single-use state also stored in Redis with the destination, TTL 10 min)
browser ── user signs in on Steam's own page (password never reaches us)
   ◄── Steam redirects to /api/auth/steam/callback?state=…&openid.*
backend: state == cookie == Redis record (single use) → mode/ns/op_endpoint/return_to
         → claimed_id == identity, Steam format → required fields signed
         → nonce fresh and unused (Redis) → check_authentication POST to Steam (is_valid:true)
         → SteamID64 → GetPlayerSummaries (best effort) → user upsert (one Steam id = one user)
         → new session (only SHA-256 stored) → queue import if last sync > 1 h
   ◄── 303 to /onboarding (or a validated same-site `next`) + session cookie
```

### Library import (`app/services/library_import.py`)

1. `GetPlayerSummaries` and `GetOwnedGames`. If the profile isn't public or the response has no
   `game_count`, the run becomes `blocked_private` and **no library rows are written**. If
   `game_count == 0`, the run becomes `empty`.
2. Every AppID resolves to one canonical game (`external_game_ids` is unique, and creation
   runs under an advisory lock).
3. Library rows are upserted. A playtime snapshot is appended for new rows and for any
   change in Steam-reported values. Games that disappear get `removed_at`.
4. Best effort: `GetRecentlyPlayedGames`, achievements for up to 10 recently played games,
   then store metadata is queued for games without fresh metadata.

The frontend's `/onboarding` page polls `/api/me`. For private libraries it explains the
exact Steam setting to change and offers "Check again" (`POST /api/me/steam/sync`).

### Metadata and taxonomy (ADR-0012, ADR-0013)

`IStoreBrowseService/GetItems` (50 apps per call) feeds name, type, description, release,
artwork, categories, user tags with vote weights, and review summaries. Raw tags go to
`game_provider_tags`, then versioned mappings derive `game_feature_values` with confidence
and evidence. `GET /api/catalogue/features/{slug}/games` queries a feature together with all
of its descendants (MAX roll-up). A provider failure marks `game_sources.status = error` and
never affects imports.

### API surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/auth/steam/login`, `GET /api/auth/steam/callback` | throttled per IP | OpenID sign-in |
| `POST /api/auth/logout` | session + Origin | Revoke session |
| `GET /api/me` | session | User, Steam connection, latest sync, library stats, `profile_ready` |
| `POST /api/me/steam/sync` | session + Origin | Re-check visibility and re-import (`steam_import` mode only; 409 otherwise) |
| `GET /api/me/library/search?q=` | session, 30/min | Search Steam's store for games, annotated with the user's state |
| `PUT /api/me/library/games/{appid}` | session + Origin | Set `{owned, rating}` for a game (sign-in-only mode, ADR-0014) |
| `GET /api/me/library` | session | Own library with catalogue data (Steam-attributed) |
| `GET /api/me/profile` | session | Gamer profile: inferred and manual preferences with confidence, components, evidence games, mode balance |
| `PUT /api/me/preferences/{slug}` / `DELETE` | session + Origin | Set or clear a manual value (−1…1) and/or exclusion; queues a rebuild |
| `GET /api/me/preferences/history?feature=` | session | Manual change log and inferred history for one feature |
| `GET /api/me/recommendations/{owned\|unowned\|trending}` | session | Latest run with items, contributions, reasons, price, reviews. Filters: `max_price_cents`, `free_only`, `min_review_pct`, `released_after`, `released_before`, `players` |
| `POST /api/me/recommendations/refresh` | session + Origin | Rebuild now (60 s cooldown) |
| `POST /api/me/events` | session + Origin, 60/min | Batch of impressions, clicks, game page views, store visits (idempotent) |
| `GET /api/me/events?before=&limit=&feedback_only=` | session | The user's own event history |
| `PUT /api/me/games/{id}/feedback/{kind}` | session + Origin | `{on, reason?, run, position, surface}`: like, dislike, favourite, save_for_later, not_interested, not_my_type, already_played; `on: false` undoes |
| `PUT /api/me/games/{id}/satisfaction` | session + Origin | Rating −2…2 or null; source `post_play` or `already_played` |
| `GET /api/me/feedback` | session | Every game with feedback or a recommendation-time rating |
| `GET /api/me/satisfaction-prompt` / `POST …/{id}` | session (+ Origin) | The one post-play question to show now; record shown, snooze or decline |
| `GET /api/me/games/{id}` | session | Game page: live Match and reasons, feedback state, latest exposure |
| `GET` / `PUT /api/me/privacy` | session (+ Origin) | Training opt-out, scheduled sync |
| `GET /api/me/export` | session, 5/h | JSON download of all personal data |
| `DELETE /api/me` | session + Origin | `{"confirm": "DELETE"}`: delete the account and all personal data |
| `GET /api/catalogue/taxonomy` | public | Canonical feature tree |
| `GET /api/catalogue/features/{slug}/games` | public | Games with a feature (hierarchy-aware) |
| `GET /api/catalogue/games/{id}` | public | Game, external ids, features with provenance |
| `GET /api/catalogue/providers` | public | Provider registry and status |

### Stage 3: profiles and recommendations (ADR-0016, [docs/RECOMMENDATIONS.md](docs/RECOMMENDATIONS.md))

```
library import succeeded ─► refresh_recommendations(user)            [queue: recommendations]
                              1. store metadata for library games missing it
                              2. profile: preference + confidence vectors  → profile_runs, user_feature_preferences
                              3. discovery (≤ 1 per 6 h): store Query by liked tags → new catalogue games + metadata
                              4. owned / unowned / trending runs           → recommendation_runs, recommendation_items
PUT /api/me/preferences/{slug} ─► same task, 5 s debounce, no discovery
POST /api/me/recommendations/refresh ─► same task, at most once a minute
beat: discover_global_candidates (daily charts) · sample_player_counts (every 2 h) · aggregate_player_counts (daily)
```

Pages read the latest stored run; filters apply when the list is read. The first visit
with no run queues a rebuild and shows a "building" state that polls until the run is ready.

### Stage 4: behaviour, feedback and collaborative learning (ADR-0017, ADR-0018)

```
browser: card ≥50% visible for 1 s ─► impression ┐
         title/art click, game page, Steam link ─┴► POST /api/me/events (batched, idempotent) → behaviour_events
feedback buttons ─► PUT /api/me/games/{id}/feedback/{kind} → user_game_reactions + event ─► rebuild (5 s debounce)
post-play question ─► PUT …/satisfaction → user_feedback + event
library sync ─► playtime_change events (attributed to the last exposure within 90 days)

beat 04:35 train_collaborative                                        [queue: training]
  eligible users (opted in) → pseudonymised signals → chronological + cold-item splits
  → popularity, content, ALS, hybrid ALS, BPR, hybrid BPR → evaluation_results
  → gates → deploy (artifact on the `models` volume) → rebuild active users
refresh_recommendations: profile (now with feedback) → candidates (content ∪ collaborative top 100)
  → Match blended with the collaborative percentile when a model applies → runs (algorithm, model_version_id)
```

Details: [docs/BEHAVIOUR.md](docs/BEHAVIOUR.md), [docs/COLLABORATIVE.md](docs/COLLABORATIVE.md),
[docs/PRIVACY.md](docs/PRIVACY.md).

### Stage 5: satisfaction model, daily training, monitoring (ADR-0019, [docs/SATISFACTION.md](docs/SATISFACTION.md))

```
beat 04:35 train_models                                               [queue: training]
  1. collaborative stage (as Stage 4)
  2. satisfaction stage: labels (ratings + weighted explicit feedback) → point-in-time
     features (as-of history, cross-fitted CF) → 70/15/15 time split → LightGBM +
     calibration vs content baseline → gates → register → deploy
  each stage → training_runs (+ JSON report) and <models>/reports/<kind>-<run>.md
beat 05:45 monitor_models → model_monitoring_reports (metrics + alerts)
refresh_recommendations: … → P(satisfied) per candidate → category ranking
  (owned 0.85·sat+0.15·backlog, unowned sat, trending 0.8·sat+0.2·trend) → runs (+sat#id)
admin: docker compose exec worker python -m app.cli train|models|report|rollback|monitor
```

### Stage 6: trend source health, completion times, hardening, performance

```
sample_player_counts (every 2 h) → player_count_samples + player_count_passes (one row per pass)
  trending generator: source freshness > 26 h or reliability < 50 % → run "unavailable" (paused);
  owned/unowned lists unaffected
refresh_completion_times (daily 03:51, only if IGDB enabled) → game_completion_times (source, fetched_at)
prune_data (daily 05:05) → old recommendation runs (latest kept), old events, old monitoring reports
```

Request path (all plain ASGI middleware, outermost first): request id + access log +
security headers → body-size limit (413/411) → general rate limit (per session /
per IP / public catalogue; Redis, fails open behind a 30 s breaker) → CSRF origin
check → FastAPI. Unhandled errors return a generic JSON 500 with the request id.

Database sessions are an **async** FastAPI dependency (closed on the event loop) and
the session check always ends its transaction, so no request holds a pooled
connection while waiting for a threadpool thread. Pool: 10 + 10 per API process,
10 s timeout. These two changes, and replacing `BaseHTTPMiddleware`, came out of the
100-user load test ([docs/PERFORMANCE.md](docs/PERFORMANCE.md)).

Outbound providers share one HTTP client with typed errors, bounded retries,
per-provider throttles, a **circuit breaker** (after an outage, calls are skipped for
2 minutes instead of each waiting through retries) and hourly outcome counters
(`app.cli status`).

Deployment: one production file, `docker-compose.yml` (Traefik labels, no published
ports, limits) running the images built by `build.sh`, plus the optional
`docker/dev/compose.dev.yaml` test overlay on workstations ([DEPLOYMENT.md](DEPLOYMENT.md),
[tutorial.md](tutorial.md)). Scoring mode: `AI_GRADE` selects the machine-learning or
classic engine in `app/recommendations/engines.py` ([docs/SCORING_MODES.md](docs/SCORING_MODES.md)). Isolated performance stack:
`perf/` (separate Compose project, synthetic data, Steam unreachable).

## 5. Frontend

```text
frontend/src/
  app/                    App Router: landing page, (app)/ route group with 7 pages, /healthz
  components/ui/          local component library (Button, Card, Badge, ...; cva + tailwind-merge)
  components/{layout,games,profile,brand}/
  lib/types.ts            UI domain types (shared by mock and real data)
  lib/data/               data-access layer: the ONLY place pages get data from
  mocks/                  fictional sample data, reachable only via lib/data
```

- **Mock isolation** ([ADR-0007](docs/adr/0007-mock-data-isolation.md)): every
  loader returns `{ source: "mock" | "api", data }`. Pages show a preview banner
  for mock data. An ESLint rule blocks importing `@/mocks` from anywhere except
  `lib/data`.
- **Scores**: until a calibrated satisfaction model exists, the UI labels scores
  "Match" and never shows them as a percentage (spec §18, §33). This is enforced
  by `ScoreBadge` and covered by a test.
- Next.js 16 with Cache Components; pages are currently prerendered static because
  their data is fixed. Real per-user data will stream inside Suspense boundaries.

## 6. Security baseline

- PostgreSQL and Redis are only on an `internal: true` network. They are never
  published and have no outbound route.
- Least-privilege database roles: the runtime role cannot run DDL ([ADR-0004](docs/adr/0004-least-privilege-database.md)).
- Containers run as non-root with a read-only root filesystem, `no-new-privileges`
  and all capabilities dropped. Postgres and Redis use their images' defaults.
- Redis requires a password, which is passed on stdin so it never appears in the process list.
- Security headers on both apps; API docs disabled in production.
- Stage 2 added: server-side sessions (hashed tokens, HttpOnly, SameSite=Lax, Secure on https),
  OpenID state/nonce replay protection, Origin checks on unsafe methods, per-IP auth throttling,
  open-redirect-safe `next`, the Steam API key kept backend-only and **never logged** (httpx
  URL logging is disabled because the key travels in the query string; a test checks this).
- Stage 4 added: per-user limits on events, feedback, search and export; account deletion
  and data export; training opt-out; pseudonymised training data; append-only event log.
- Stage 6 added: general API rate limiting, request-size limits, sanitised 500s, session
  idle expiry and "sign out other devices", retention, provider circuit breaker,
  `scripts/security-check.sh` (dependencies, secrets, exposure, containers, headers).
  Full list: [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md).
- Not yet implemented: dependency scanning in CI (run the script before each release).

## 7. Planned evolution

| Stage area | Lands in |
|---|---|
| ~~Relational schema, Steam OpenID, platform adapter, Celery~~ | done in Stage 2 |
| ~~Daily training jobs~~ | done in Stage 4 (`training` queue) |
| ~~Content-based baseline, profiles, three categories, real data in the UI~~ | done in Stage 3 |
| ~~Collaborative filtering~~ | done in Stage 4 (deploys once enough real players exist) |
| ~~LightGBM satisfaction model, daily training, monitoring~~ | done in Stage 5 (deploys once 200 labels exist) |
