# Testing report (Stage 6)

Date: 2026-11-15. Every result below comes from a run on this date against the
current working tree. Nothing is assumed from earlier stages.

## Summary

| Check | Command | Result |
|---|---|---|
| Backend unit + integration tests | `docker compose --profile test run --rm backend-tests` | **241 passed** (166 unit, 75 integration) |
| Backend lint, format, types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` | Clean (mypy: 112 application files; the test files are not type-checked clean) |
| Frontend tests | `npm test` | **54 passed** |
| Frontend typecheck, lint, production build | `npm run typecheck && npm run lint && npm run build` | Clean; build succeeded |
| Compose configuration | `docker compose config -q` (at Stage 6: base, production and perf overlays; since consolidated into `docker-compose.yml`) | All valid |
| End-to-end smoke test | `./scripts/smoke-test.sh` | **38/38** |
| Security checks | `./scripts/security-check.sh` | **Passed** (29 checks, below) |
| Backup and restore rehearsal | `./scripts/backup-db.sh` then `./scripts/restore-db.sh` into a scratch database | **OK**: migration 0007, row counts match, runtime role can read, 4.85 s |
| Browser inspection | `scripts/browser-check.py` (headless Chromium) | 32 page loads, no errors, no overflow (below) |
| Performance, 100 concurrent users | `perf/run_final.sh` | **0 errors** in all three scenarios ([PERFORMANCE.md](PERFORMANCE.md)) |

## Automated tests

Backend tests run in Docker against a dedicated `wdywtp_test` database and a real Redis
(separate logical database). They never touch development data, and Steam is replaced
by recorded fixtures and fakes (`tests/fakes.py`, `tests/fixtures/steam`).

| Area | Files | What they prove |
|---|---|---|
| Sign-in and sessions | `test_openid.py`, `test_auth_service.py`, `test_auth_flow.py`, `test_signin_only_mode.py` | OpenID assertion verification, single-use state and nonces, replayed callbacks rejected, open redirects blocked; logout revokes the session; sessions listed, revoked elsewhere and expired when idle |
| Library import | `test_library_import.py`, `test_manual_library.py`, `test_steam_clients.py` | First import and re-sync, private profiles, hidden playtime, retries, throttling, no-key fallback |
| Catalogue | `test_catalogue.py`, `test_taxonomy.py` | Shared canonical games, metadata ingestion and attribution, taxonomy mapping |
| Profiles and recommendations | `test_recommendation_engine.py`, `test_recommendations.py`, `test_feedback_learning.py` | Profile signals, Match formula, three lists, exclusions as hard filters, explanations matching the actual rating ("loved" vs "liked") |
| Behaviour and collaborative learning | `test_behaviour_learning.py` | Event logging, feedback adapting profiles, pseudonymised datasets, opt-out excluded, deployment gates |
| Satisfaction and daily training | `test_satisfaction_model.py`, `test_satisfaction_training.py` | Point-in-time features with no leakage, calibration, gates, versioning, rollback, training duration recorded |
| Release hardening | `test_hardening.py`, `test_origin_check.py`, `test_release.py`, `test_health.py`, `test_config.py` | Rate limits (general and per action), body limits, CSRF origin check, error handler (no internals leaked), provider circuit breaker, trend staleness and reliability gates, sampling passes, completion-time attribution, list `limit`/`total`, retention (unshown runs after 24 h, shown runs kept for 90 days), sessions |
| Stack | `test_stack.py` | Runtime database role cannot create tables, migrations downgrade and upgrade, Redis round trip, readiness endpoint |

Frontend tests (Vitest + Testing Library, 10 files) cover the API client and data
mapping, score wording ("Match" vs "Predicted enjoyment", "<1%"/">99%"), list status
wording per engine, feedback controls, the sessions control and page components.

## Security checks

`scripts/security-check.sh` verifies, on the running stack:

- **Dependencies**: pip-audit (58 pinned packages) and npm audit (production) report no
  known vulnerabilities.
- **Secrets**: `.env` untracked and mode 600; the Steam key appears in no tracked file;
  no private keys in the repository.
- **Exposure**: only the backend and frontend publish ports, on loopback only; Postgres,
  Redis, worker and scheduler publish none; the internal network has no outside route.
- **Containers**: all application containers run as non-root users with read-only root
  filesystems.
- **Headers**: API and web app send `nosniff`, `X-Frame-Options`, `Referrer-Policy`;
  the API sends a deny-all CSP; the web app hides `X-Powered-By`.

The manual review is in [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md).

## Browser inspection

The Chrome extension was not connected, so the check used headless Chromium
(Playwright 1.64.1) through `scripts/browser-check.py`. It loads the dashboard,
trending, buy, play, profile, settings, a game page and the home page at desktop
(1440×900) and phone (390×844) sizes, takes full-page screenshots, and records console
errors, failed requests and horizontal overflow.

| Account | Loads | Console errors | Failed requests | Overflow | Interactions |
|---|---:|---:|---:|---:|---|
| Real account (dev stack; read-only, temporary 15-minute session deleted afterwards) | 16 | 0 | 0 | 0 px | None (read-only) |
| Synthetic account (perf stack) | 16 | 0 | 0 | 0 px | Like then undo (pressed → not pressed); "Sign out other devices" (2 sessions → 1, confirmation shown) |

Problems the inspection found, all fixed and re-checked:

| Problem | Fix |
|---|---|
| Trending "Popular right now" cards 72 px wider than a phone screen | Single-column grid with shrinkable items and a smaller cover on phones |
| Game page said "Recommended in From your library" | Proper list names ("Games I Should Play", "Games I Should Buy", "Trending Games") |
| Card score differed from the game page (64 vs 58): cards showed the internal ranking score | Cards show the Match or predicted enjoyment; the ranking score is kept separately |
| "Similar to X, which you loved" when the rating was Liked | Wording follows the actual rating |
| Sessions list hidden for accounts without a linked library | Shown to every signed-in user |
| "Predicted enjoyment 0%" for very low probabilities | Shown as "<1%" (and ">99%") |
| List status still said "content-based baseline" with models deployed | Wording follows the engine actually used |

The overflow check itself was validated on test pages: a real overflow is reported
(72 px), while ellipsis truncation and the horizontally scrolling phone nav are not.

## Real Steam data

On the development stack with the operator's Steam key, three sign-ins on 2026-11-15
(10:18, 11:38, 13:16 UTC) each imported the owner's library of **539 games** with
playtime, and 18 profile builds ran. The owner has rated 14 games and given 8
dislikes. With one real player, both models correctly decline to train (gates need 25
players and 200 labels), so recommendations on real data use content Match.

## Not verified

- **Deployment on the real Linux server** behind Traefik with HTTPS and the real domain.
  The production overlay validates and runs locally, but not on the server.
- **Models trained on real players**: training, calibration and deployment are verified
  on synthetic data only.
- **IGDB completion times** against the live service (disabled until credentials and
  terms are confirmed); covered by tests with canned IGDB responses.
- **Trend scores on real data**: need 42 days of player-count samples (about 2026-12-27);
  freshness and reliability gates are tested.
- **Real browsers and devices** beyond headless Chromium (Safari, Firefox, real phones).
- **Long-running behaviour**: load tests ran for 3 minutes each; no soak test.

## Update: AI_GRADE and single Compose file (2026-11-15)

Re-run after the AI_GRADE scoring mode (ADR-0020) and the Compose consolidation
(ADR-0021), on the final working tree.

| Check | Result |
|---|---|
| Backend tests (Docker, isolated test database) | **274 passed** (incl. 27 unit + 5 integration AI_GRADE tests, config secret-hiding test) |
| Backend lint, format, types | `ruff check`, `ruff format --check`, `mypy app` (113 files): clean |
| Frontend | 56 tests passed; typecheck, lint clean; production build exit 0 |
| Compose | Production `docker-compose.yml` renders with a production `.env`: 7 services, no published ports, PostgreSQL and Redis only on `internal`, external `proxy` network from `TRAEFIK_NETWORK`, 3 named volumes, limits and restart policies on every long-running service, scheduler/backend/worker wait for `migrate`. Workstation overlay and perf overlay also valid |
| Environment validation | `scripts/check-env.sh` rejects invalid `AI_GRADE`, placeholder passwords, empty hostname, http URL, unknown Traefik network, malformed Steam key; accepts `AI_GRADE=false`. `app.cli check-config` rejects invalid `AI_GRADE` and http URLs in production, without printing secrets |
| Smoke test (workstation stack) | 38/38 |
| Security check (workstation stack) | Passed (31 checks); production-mode run on the test deployment also passed (no published ports) |
| AI_GRADE live (isolated perf stack, synthetic players, both models deployed) | AI: lists `content-v2+cf#1+sat#2` with predicted enjoyment. → FALSE: AI lists hidden (`pending`), rebuilt as `content-v2`, no predictions, scheduled training and monitoring `skipped`, models and registry intact. → TRUE: rebuilt with the same deployed models |
| Deployment test (fresh copy, fresh volumes, local Traefik v3.6) | Routing, HSTS, TLS (Traefik default certificate), persistence, restarts, backup, restore rehearsal, restore over live, restore onto a second deployment with different secrets, DB and Redis password rotation, migration downgrade/upgrade, AI_GRADE switch and invalid value |

Not verified here: a real ACME certificate, the real server and domain, rotation of
`DB_MIGRATION_PASSWORD` and `POSTGRES_SUPERUSER_PASSWORD` (same `ALTER ROLE` mechanism
as the tested `DB_PASSWORD` rotation), and Steam sign-in plus library import through
the new production layout with the owner's account (the workstation stack's earlier
real imports used the same code).
