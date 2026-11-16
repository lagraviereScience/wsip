# Stage 6 report: trending data, production hardening and release

> **Later change (AI_GRADE and deployment tutorial):** the three Compose files named
> below (`compose.yaml`, `compose.prod.yaml`, `compose.traefik.yaml`) and
> `.env.production.example` were consolidated into one production `docker-compose.yml`
> and one `.env.example`. Install and operate with [tutorial.md](../../tutorial.md).

Prompt: [docs/spec/prompts/PROMPT_6_TRENDING_HARDENING_RELEASE.md](../spec/prompts/PROMPT_6_TRENDING_HARDENING_RELEASE.md) · Date: 2026-11-15

Evidence: [TESTING.md](../TESTING.md) · [PERFORMANCE.md](../PERFORMANCE.md) ·
[SECURITY_CHECKLIST.md](../SECURITY_CHECKLIST.md) · [BACKUP_AND_RECOVERY.md](../BACKUP_AND_RECOVERY.md) ·
Documentation index: [docs/README.md](../README.md)

## Verdict

**Stage 6 meets its acceptance criteria partially: 10 PASS, 5 PARTIAL, 0 FAIL.**

Everything that can be verified on this machine has been verified by running it. The
five partial criteria are partial for two reasons:

- **Not enough real players yet.** There is one real player, and the models need 25
  players and 200 ratings, so global learning and satisfaction prediction are proven on
  synthetic players only.
- **Things that need time or the real server.** Trend history needs 42 days of samples
  (about 2026-12-27), the first scheduled daily training runs on 2026-11-16 at 04:35 UTC,
  and the app hasn't been deployed on the real server behind HTTPS.

No criterion fails, and none is marked PASS just because the code exists.

The app supports **100 concurrent signed-in users with zero errors**: p95 0.26 s at
realistic pacing and 0.75–0.82 s under aggressive pacing. This includes while daily
training, library syncs and rebuild bursts run. This was measured on this host with the
production CPU and memory limits, not on the target server.

## Acceptance criteria

"Real" means the owner's own account and data on the development stack. "Synthetic"
means the isolated `wdywtp-perf` stack or the test database, with no calls to Steam.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Authenticate users through Steam | **PASS** | **Real:** Steam OpenID sign-ins at 10:18, 11:38 and 13:16 UTC, each creating a session. Tests: assertion verification, single-use state and nonce, replay rejected, open redirect blocked, logout revokes, session list, revoke elsewhere and idle expiry (`test_openid`, `test_auth_service`, `test_auth_flow`, `test_release`). Browser: "Sign out other devices" went from 2 sessions to 1 |
| 2 | Validate public game details | **PASS** | **Real:** the owner's public game details were detected and imported. Two earlier runs failed cleanly with `steam_api_key_missing` before the key was set. Tests: a private profile blocks the import even when the API returns games; onboarding explains it and a retry succeeds after making details public; an empty visible library and hidden playtime are reported (`test_library_import`, `test_auth_flow`) |
| 3 | Import actual gaming libraries | **PASS** | **Real:** 4 successful imports of the owner's **539-game** library with playtime (last at 13:16 UTC). **Synthetic:** a 450-game first import p50 1.33 s, a re-sync with 60 changes p50 0.45 s, 190 imports/min |
| 4 | Build individual gamer profiles | **PASS** | **Real:** 18 profile builds from the real library, ratings and reactions; the profile page renders without errors on desktop and phone. Tests: numeric profile with confidence; history records only changes |
| 5 | Maintain a shared canonical game catalogue | **PASS** | **Real:** 986 canonical games, 14,242 feature values, store metadata for 960 (26 not found on the store), 960 review summaries, 440 prices, each with source and timestamp. Tests: concurrent creation never duplicates, merging duplicates, raw tags re-mapped when the taxonomy changes. **Synthetic:** 420 players sharing 1,200 games |
| 6 | Analyse playtime by canonical feature | **PASS** | **Real:** profiles are built from playtime per canonical feature (lifetime and recent) over the 539 games, with 3 manual preferences applied. Tests: behavioural lift per feature, explanations traced to features (`test_recommendations`, `test_recommendation_engine`) |
| 7 | Generate the three recommendation lists | **PARTIAL** | **Real:** "Games I Should Play" and "Games I Should Buy" have 60 items each (latest build 13:17 UTC). "Trending Games" is **empty by design**: trend scores need 42 days of player-count history (3,200 samples of 472 games since 00:30 UTC; ready about 2026-12-27). Until then a labelled "Popular right now" list is shown and no trend is invented. **Synthetic:** all three lists generated and served (unowned p50 196 ms, owned 39 ms, trending 37 ms per build). Tests: trend growth from collected history, unavailable without history, stale or unreliable sources pause trending only |
| 8 | Learn from explicit and implicit behavioural information | **PASS** | **Real:** 14 ratings, 8 dislikes and 105 behaviour events recorded, and the profile adapts to them. Playtime changes between syncs are recorded with attribution. Tests: feedback updates the profile while manual preferences stay authoritative; impressions are distinct from clicks; the event log is append-only; clicks never become satisfaction labels |
| 9 | Use global and individual personalisation | **PARTIAL** | Individual: **real** (above). Global (collaborative model): **synthetic only**. Deployed on the perf stack (`cf-20261115-133500-hybrid_als`) and served under load (`content-v2+cf`). On real data it correctly declines to train: 1 player, 25 needed. Tests: training excludes opted-out players; serving blends the model and falls back to content on cold start |
| 10 | Prioritise actual satisfaction | **PARTIAL** | **Synthetic:** a calibrated LightGBM satisfaction model (`sat-20261115-133500-lgbm`) is deployed on the perf stack and ranks all three lists (`+sat`, shown as "Predicted enjoyment"). Labels are explicit judgements only. **Real:** 14 ratings (200 needed), so ranking uses Match, in which those ratings are profile signals. The card labels say which score is shown |
| 11 | Retrain models daily | **PARTIAL** | The `train_models` schedule is configured (04:35 UTC) and the scheduler is running. **Real:** manual runs today correctly skipped (not enough data). No *scheduled* run has happened yet; the first is 2026-11-16 04:35 UTC. **Synthetic:** a full daily run trains, evaluates, registers and deploys both models in 21.5 s (23.5 s under 100-user load). Tests: `test_daily_pipeline_trains_evaluates_registers_and_deploys` |
| 12 | Retain previous production models | **PASS** | **Synthetic:** the training run during the load test scored worse (AUC 0.836 vs 0.869), so the gate kept the production model and serving was unaffected. Five versions are retained. Tests: `test_rollback_redeploys_an_earlier_version`; `test_insufficient_data_keeps_the_deployed_model_and_failures_never_stop_serving`. CLI: `python -m app.cli rollback` |
| 13 | Respect user preferences and exclusions | **PASS** | **Real:** none of the 8 disliked games appears in any list built after the dislike (checked by query: 0 rows); 3 manual preferences applied. Tests: excluded tags respected everywhere, explicit negatives are hard filters, manual preferences override learning |
| 14 | Run on the Linux server through Docker Compose | **PARTIAL** | Runs on Linux (WSL2) with Docker Compose. **Verified:** a 6-service stack, all healthy; production overlay valid; health checks; restart policies; CPU and memory limits (exercised in the load test); persistent named volumes; migrations (0007) and a backup/restore rehearsal; non-root, read-only containers; database and Redis not published (security check). **Not verified:** the actual server, the Traefik HTTPS route and the real domain |
| 15 | Remain useful when external providers are unavailable | **PASS** | **Synthetic:** the whole 100-user load test ran with Steam **unreachable** and IGDB disabled, with 0 errors; the circuit breaker skips a failed provider for 2 minutes instead of stalling workers. Tests: store outage does not break imports; provider outage fails a sync run cleanly; a stale or unreliable player-count source pauses only trending; the rate limiter fails open when Redis is down; IGDB stays off without credentials |

## What Stage 6 added

| Prompt section | Delivered | Where |
|---|---|---|
| A. Trending | Player-count history (Steam's own API), daily aggregates, recent average, historical comparison, growth, acceleration; **freshness and reliability** recorded for every sampling pass and shown on the trending page; trend scores pause at 26 h staleness or below 50% reliability. SteamCharts and SteamDB were evaluated and **not used** (no API; scraping not permitted or not assumed) | [PROVIDERS.md](../PROVIDERS.md), [RECOMMENDATIONS.md](../RECOMMENDATIONS.md) |
| B. Metadata | Descriptions, artwork, genres, tags, reviews, prices and discounts from Steam with attribution and timestamps. Completion times via an IGDB adapter with attribution, **disabled** until the owner confirms IGDB's terms and adds credentials | [PROVIDERS.md](../PROVIDERS.md) |
| C. Hardening | Session idle expiry, session list and "sign out other devices"; general and per-action rate limits; body-size limits; CSRF origin check; JSON errors without internals; structured logs with request IDs; model monitoring; backups with a restore rehearsal; retention; data export and deletion; security check script; provider circuit breaker | [SECURITY_CHECKLIST.md](../SECURITY_CHECKLIST.md), [BACKUP_AND_RECOVERY.md](../BACKUP_AND_RECOVERY.md) |
| D. Deployment | `compose.prod.yaml` (production mode, limits) with `compose.traefik.yaml` (HTTPS, no published ports); `.env.production.example`; secrets validated at start | [DEPLOYMENT.md](../../DEPLOYMENT.md) |
| E. Performance | Isolated perf stack, Locust scenarios, resource monitoring; 8 bottlenecks fixed | [PERFORMANCE.md](../PERFORMANCE.md) |
| F. Documentation | All eleven documents in the list; mapping in the docs index | [docs/README.md](../README.md) |

## Changes made while resuming Stage 6

Performance fixes, all covered by tests and re-measured:

- async database session dependency and a larger pool with a timeout (the pool deadlock);
- the four middlewares rewritten as plain ASGI;
- list `limit` and `total`;
- one session lookup per page;
- keep-alive of 95 s on both servers;
- the provider circuit breaker;
- a direct ratings query in the satisfaction features (559 → 51 ms);
- deleting never-shown recommendation lists after 24 h.

Correctness fixes found on the way:

- training runs recorded 0 s duration;
- explanations said "loved" for a Liked rating;
- cards showed the ranking score instead of Match;
- the game page said "Recommended in From your library";
- a mobile overflow on the trending page;
- the sessions list was hidden without a linked library;
- "0%" predicted enjoyment;
- stale engine wording.

## Validation run (2026-11-15)

| Check | Result |
|---|---|
| Backend tests | 241 passed (166 unit, 75 integration); ruff, format, mypy clean |
| Frontend | 54 tests passed; typecheck, lint and production build clean |
| Compose | Base, production and perf configurations valid |
| Smoke test | 38/38 |
| Security check | Passed (29 checks; pip-audit and npm audit clean) |
| Backup and restore | Rehearsal OK: migration 0007, counts match, runtime role reads, 4.85 s |
| Browser | 32 page loads (real account read-only, synthetic account with interactions), desktop and phone: no console errors, failed requests or overflow |
| Performance | 100 users: 0 errors in all scenarios; see [PERFORMANCE.md](../PERFORMANCE.md) |

## Not done or not verified

- **Real-server deployment** with Traefik, HTTPS and the real domain (OPEN_QUESTIONS #14).
- **Models on real data**: need 25 players and 200 ratings (OPEN_QUESTIONS #28, #29).
- **Trend scores on real data**: need 42 days of samples, about 2026-12-27 (#22).
  Sampling passes are recorded from the next run (16:15 UTC); the passes before the
  workers were restarted with Stage 6 code predate that table.
- **First scheduled daily training**: 2026-11-16 04:35 UTC.
- **IGDB completion times**: disabled until terms and credentials are confirmed (#34).
- **Legal review** of Steam data terms and training consent (#15, #25).
- **Real browsers and devices**: the check used headless Chromium because the Chrome
  extension was not connected (#36).
- **Soak testing**: load tests ran for 3 minutes each.

## State of the machine

- Nothing is committed (the directory is not a git repository).
- The development stack is running with the current images.
- The isolated perf stack (`wdywtp-perf`, ports 3100/8100) is still running with its
  synthetic data. Remove it and its volumes with `./perf/stack.sh down`; it does not
  touch the development stack or the `portfolio-website` network.
