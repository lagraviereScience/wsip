# Performance report (Stage 6)

Date: 2026-11-15 · Tooling: [`perf/`](../perf/) · Raw summaries: [`perf/results/`](../perf/results/)

## Summary

- **100 concurrent signed-in players are supported with zero errors** in every final
  scenario, including while the daily training, 20 library syncs and a burst of 100
  recommendation rebuilds ran at the same time.
- Under aggressive pacing (one action every ~2 s per player, 47 requests/s at the
  client) the 95th-percentile response time is **0.75–0.82 s**. With realistic pacing
  (5–15 s between actions) it is **0.26 s**, with a median of 29 ms.
- The first test run did **not** support 100 users: 3.1% errors and requests waiting up
  to 110 s. Eight bottlenecks were found and fixed (below).
- The remaining limit is the API's 2-CPU allowance under aggressive pacing. Scaling
  options are listed at the end.

## Environment

| | |
|---|---|
| Host | 24 CPUs, 31 GB RAM (Windows WSL2, Docker Desktop); one machine runs the stack and the load generator |
| Stack | The production images with the **same CPU and memory limits** as the Compose file at the time: API 2 CPUs / 1 GB (2 uvicorn processes), worker 2 CPUs / 1 GB (3 processes), frontend 1 CPU, Postgres 2 CPUs |
| Isolation | Separate Compose project `wdywtp-perf` (own database, Redis, model volume, networks; ports 3100/8100; `perf/stack.sh`). Steam is unreachable from it (API base URL points at a closed port, no key), the scheduler is off, and IGDB is disabled. No request reached Steam or IGDB. The real dev stack and data were not touched |
| Data | Synthetic only (`perf/seed.py`): 420 players, 400 with 40-game libraries and 20 with 450-game libraries (real-library size); 1,200 games; 22,376 library entries; 6,042 ratings; 3,082 reactions. Both models trained and deployed on it, so serving used the heaviest path (content + collaborative + satisfaction) |
| Load tool | Locust 2.47.0 (`perf/locustfile.py`): each virtual user is a different signed-in synthetic player. Pages hit the web app (server-rendered), and API calls hit the backend directly, as Traefik routes `/api` in production |
| Mix per user | dashboard 3, buy/play/trending/profile/game pages 1 each, recommendations API 3, game API 2, impression batches 2, profile API 1, like + undo 1 |
| Resources | `perf/monitor.sh`: `docker stats`, Postgres activity and commits, Redis memory, ops and queue lengths, Celery active tasks, every 5 s |

Reproduce: `./perf/stack.sh up`, seed (see `perf/seed.py`), then `./perf/run_final.sh`.

## Final results

| Scenario | Requests | Errors | p50 | p95 | p99 | Throughput |
|---|---:|---:|---:|---:|---:|---:|
| **A. 100 players, aggressive** (1–3 s think time), 3 min | 8,473 | **0** | 130 ms | 820 ms | 1.4 s | 47.3 req/s |
| **B. Same, during background work**: daily training + 20 library syncs (450 games) + 100 rebuilds | 8,518 | **0** | 120 ms | 750 ms | 1.2 s | 47.5 req/s |
| **C. 100 players, realistic** (5–15 s think time), 3 min | 1,997 | **0** | 29 ms | 260 ms | 430 ms | 11.1 req/s |

Scenario B is the "responsive during background training" check: page and API
latency did not get worse while the worker ran at its full 2 CPUs.

### Per request type (scenario A)

| Request | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|
| API: recommendations (any list) | 67 | 460 | 670 |
| API: game page data | 61 | 420 | 590 |
| API: profile | 47 | 400 | 580 |
| API: impression batch (5 events) | 48 | 350 | 580 |
| API: like + undo | 57 | 420 | 650 |
| Page: dashboard (7 backend calls) | 290 | 1,100 | 1,800 |
| Page: profile | 280 | 1,400 | 1,800 |
| Page: buy / play / trending / game | 160–270 | 850–1,100 | 1,200–1,700 |

### Resources (peaks; means in brackets)

| Container | A: CPU % | B: CPU % | C: CPU % | Memory peak |
|---|---|---|---|---|
| API (limit 200%) | 200 (155) | 200 (131) | 59 (27) | 318 MiB / 1 GiB |
| Frontend (limit 100%) | 94 (71) | 98 (63) | 47 (17) | 215 MiB / 768 MiB |
| Postgres | 94 (66) | 112 (76) | 83 (26) | 511 MiB / 2 GiB |
| Worker (limit 200%) | 202 (119) | 201 (196) | 200 (100) | 638 MiB / 1 GiB |
| Redis | 5 (2) | 4 (2) | 1 (1) | 12 MiB / 768 MiB |

- **Database**: at most 39 connections (runtime role limit 60) and at most 2–3
  concurrently active queries. Cache hit rate ≥ 99.9%; 370 commits/s at peak.
- **Redis**: under 2 MiB and 585 ops/s at peak.
- **Queues**: in scenario B, 100 rebuilds queued at once (peak 128 with the players' own
  feedback rebuilds) drained in 52 s while serving the load (115/min; unowned list p50
  479 ms vs 196 ms idle). Imports and training never queued.
- **Worker utilisation**: 3 of 3 processes busy throughout B. Training, syncs and
  rebuilds shared the worker without starving each other.

## Background work

| Job | Result |
|---|---|
| **Daily training** (both stages, on the synthetic dataset) | **21.5 s** idle, **23.5 s** during scenario B; CPU only, single-threaded. The run during B was evaluated but not deployed: AUC 0.836 vs production 0.869, so the gate kept the production model |
| **Recommendation generation** (profile + 3 lists, both models) | Unowned list p50 196 ms, owned 39 ms, trending 37 ms |
| **Queue burst**: 100 rebuilds queued at once | Drained in **16.2 s** (**371 rebuilds/min**) with 3 worker processes; worker CPU-bound, database idle (≤ 1 active query) |
| **Library sync** (fake Steam adapter, 450-game library, 3 in parallel) | First import p50 **1.33 s**; re-sync with 60 playtime changes p50 **0.45 s**; **190 imports/min** |
| **Model inference** per player | Load the satisfaction model and the player's features 51–63 ms; collaborative fold-in 5–10 ms; predict 287–676 candidates **8–17 ms** |

### Database queries (median of 5, ms; typical player / heavy player)

| Query | Typical | Heavy (450 games) |
|---|---:|---:|
| Recommendation list view (60 items, live price and review joins) | 3.4 | 5.1 |
| Latest run lookup | 0.8 | 0.6 |
| Hidden games (explicit negatives) | 0.4 | 0.4 |
| Feedback overview | 1.2 | 1.1 |
| Event history (50) | 2.1 | 1.5 |
| Play records (profile input) | 0.7 | 2.3 |
| Inferred preferences | 0.4 | 1.2 |
| Satisfaction-question eligibility | 1.7 | 1.3 |
| Catalogue vectors (all 1,200 games) | 14 | — |
| Training signals (all eligible players) | 223 | — |

Every page query is under 6 ms; nothing needs an extra index at this scale.

## Bottlenecks found and fixed

| # | Problem (how it showed) | Fix | Effect |
|---|---|---|---|
| 1 | **Connection-pool deadlock**: 3.1% errors (`QueuePool limit … timed out`), requests waiting up to 110 s, while Postgres had ≤ 2 active queries. Requests held a pooled connection while waiting for a threadpool thread (sync session dependency clean-up, and the session check not ending its transaction) | Async session dependency (closed on the event loop); session check always commits; pool 10 + 10 per process with a 10 s timeout | Errors 3.1% → 0.16%; p99 110 s → 3.5 s |
| 2 | **API CPU saturated**: `BaseHTTPMiddleware` ×4 cost ~6 ms of CPU per request | Rewrote the four middlewares as plain ASGI | `/api/me` 19 → 10 ms of CPU; unowned list 38 → 24 ms |
| 3 | **Over-fetching**: the dashboard fetched three full 60-item lists to show a few cards | `limit` parameter (plus `total` for "Show all"); pages ask for what they show | Smaller responses, less serialisation |
| 4 | **Duplicate session lookups**: `/api/me` called 3–4 times per page (each component asked) | `getCurrentUser` memoised per request (React `cache`) | Dashboard 9 → 7 backend calls, buy 4 → 2; throughput 35.7 → 47.8 req/s, p95 2.0 → 0.77 s |
| 5 | **Keep-alive races**: sporadic "remote end closed connection" (servers' 5 s keep-alive is shorter than the proxy's 90 s idle timeout) | uvicorn and Next.js keep-alive set to 95 s | Errors → 0 |
| 6 | **Steam outage stalls the worker**: with Steam unreachable, every rebuild waited through metadata retries and backoff (worker at 0% CPU, ~20 s per rebuild) | Provider **circuit breaker**: after a provider fails through all retries, calls to it are skipped for 2 minutes | Rebuilds stay fast during outages; sampling passes don't hang |
| 7 | **Rebuild cost grew with the player count**: the satisfaction model loaded every eligible player's full history (libraries, snapshots, events) to get other players' ratings (~0.6 s per rebuild at 420 players) | A direct query for just those ratings | Model + features 559 → 51 ms; 100-rebuild burst 43 s → 16 s |
| 8 | **Storage growth**: every feedback click rebuilds three lists (8,331 runs, 270 MB for 100 players in an hour of testing); most are replaced before anyone sees them | Retention deletes never-shown lists after 24 h (shown ones after 90 days; latest always kept) | Dry run on the perf database: 7,605 of 8,631 runs (88%) would be deleted |

Load-test evolution (scenario A, aggressive pacing):

| Run | Change | Errors | p50 | p95 | p99 | req/s |
|---|---|---:|---:|---:|---:|---:|
| 1 | Baseline | 3.10% | 110 ms | 5.2 s | 110 s | 12.8 |
| 2 | + #1 pool fix | 0.16% | 1.0 s | 2.5 s | 3.5 s | 32.0 |
| 3 | + #2 ASGI middleware | 0.13% | 840 ms | 2.2 s | 3.0 s | 34.5 |
| 4 | + #3 limits, API keep-alive | 0.03% | 780 ms | 2.0 s | 2.9 s | 35.7 |
| 5 | + #4 one session lookup per page | 0.05% | 100 ms | 770 ms | 1.6 s | 47.8 |
| Final | + #5 frontend keep-alive | **0.00%** | 130 ms | 820 ms | 1.4 s | 47.3 |

## Remaining limits and scaling

- **API CPU** is the limit under aggressive pacing (200% of 200%). On a server with
  spare CPUs, raise the API's `cpus` and `WEB_CONCURRENCY` together, keeping
  `WEB_CONCURRENCY × 20 + worker` under the database role's 60 connections (lower
  `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, or raise the role's limit).
- **Worker CPU** bounds how fast rebuild bursts drain (about 370 per minute). Training
  and syncs share the same 3 processes; a separate training worker is the next step if
  training grows.
- **Profile page** is the slowest page (p95 1.4 s under aggressive load): about 150
  preferences plus the taxonomy and the feedback list.
- Not measured: real network latency (all on one host), HTTPS termination (Traefik),
  the real Steam API under load (deliberately not called), more than 420 players or
  1,200 games, and long-run memory growth (tests ran 3 minutes each).
