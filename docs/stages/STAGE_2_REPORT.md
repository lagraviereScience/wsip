# Stage 2 report: Steam authentication, library import and game catalogue

Prompt: [docs/spec/prompts/PROMPT_2_STEAM_AUTH_LIBRARY_CATALOGUE.md](../spec/prompts/PROMPT_2_STEAM_AUTH_LIBRARY_CATALOGUE.md) · Date: 2026-11-14

## Product decision during the stage: sign-in only (ADR-0014)

After the live sign-in worked, the product owner decided not to use a Steam Web API key.
Verified live: without a key `GetOwnedGames` returns 401, and the old key-free games XML
now serves an HTML page (reading it would be scraping). There is no authorised key-free
way to read libraries. The app now runs in **sign-in-only mode**: users search Steam's
store, tick the games they own and rate the games they've played (spec §18 scale). The
automatic import path is kept, tested and switched off. Adding a key re-enables it.

**Reversed on 2026-11-15 (ADR-0015).** The owner clarified that automatic import after sign-in
is the main feature. They registered an operator key, and a live import of their library
succeeded (see Verification). Manual mode remains only as a no-key fallback.

## Research done before implementing

| Topic | Finding | Effect |
|---|---|---|
| Steam OpenID (partner docs) | OP endpoint `https://steamcommunity.com/openid/`; the SteamID is in the claimed id | ADR-0008 verifier |
| Steam Web API terms | 100k calls/day; fetch user data only at the user's request; privacy policy must disclose stored data | Throttle 60/min; scheduled sync only for recently active users with an opt-out flag; legal item OPEN_QUESTIONS #15 |
| Private vs empty library | `GetOwnedGames` returns `{"response":{}}` when hidden and `game_count: 0` when empty | `LibraryVisibility` PRIVATE / EMPTY |
| Steam tags | Not in `appdetails`; `IStoreBrowseService/GetItems` returns tags with vote weights (verified live) | ADR-0013 |
| IGDB | Free for non-commercial use; commercial use needs a partnership; FAQ wording contradicts the docs | Disabled adapter; written confirmation needed (docs/PROVIDERS.md) |
| Next.js 16 auth with Cache Components | Session reads must sit behind `<Suspense>`; never catch the `cookies()` prerender interruption | Pages are partial prerenders with streamed session content |

## Delivered

**Backend**
- Steam OpenID 2.0 sign-in: single-use state bound to an HttpOnly cookie and Redis, exact `return_to`/`op_endpoint`/claimed-id validation, signed-field check, nonce freshness and replay protection, server-to-server `check_authentication`, open-redirect-safe `next`, per-IP auth throttling.
- Server-side sessions (only SHA-256 hashes stored), logout and revocation, Origin-check CSRF defence on unsafe methods (ADR-0010).
- Users created automatically on first sign-in. SteamID64 stored. Public profile (persona name, avatar, profile URL, visibility) from `GetPlayerSummaries`. One Steam account maps to exactly one user.
- Platform adapter interface (spec §29) with the Steam implementation.
- Celery worker and beat scheduler (ADR-0011): library import, store metadata ingestion, vocabulary refresh, scheduled re-sync, session cleanup.
- Library import: owned games, AppIDs, names, total and 2-week playtime (minutes), last played, achievements for recently played games, append-only snapshots, removed-game tracking, private and empty detection, typed failure codes.
- Resilience: bounded retries with backoff and jitter, `Retry-After` support, typed provider errors, a shared Redis throttle per provider, catalogue metadata cached in PostgreSQL (refreshed after 7 days), vocabulary refreshed daily.
- Catalogue: canonical games, `external_game_ids` (Steam AppID first), `game_sources` provenance, review summaries, concurrency-safe creation, `merge_games` duplicate resolution.
- Taxonomy (ADR-0012): 6 categories, 160 hierarchical features, 284 versioned Steam tag and category mappings with confidence. Raw tags stored, derived values with evidence, hierarchy-aware queries, automatic re-mapping when the mapping version changes.
- Provider registry with documented status for 8 providers (docs/PROVIDERS.md).

**Frontend**
- A real "Sign in through Steam" flow, a user menu with sign-out, and `/onboarding` with live import status. For private libraries it shows step-by-step Steam privacy instructions and a "Check again" button. Empty and failed states and a hidden-playtime warning are covered too.
- `/signin/error` with human-readable reasons.
- Library page shows real data (artwork, playtime, achievements, top canonical features, Steam store links, Steam attribution).
- Dashboard, profile and settings show real stats, sync status and the Steam connection. Recommendation cards stay **Sample**-labelled.

**Infrastructure**: `worker`, `scheduler` and `test-db-init` services; an isolated `wdywtp_test` database and separate Redis DBs for tests; `migrate` also syncs the taxonomy; idempotent `provision.sh`.

## Verification

| Check | Result |
|---|---|
| Backend tests in Docker (`backend-tests`) | **118 passed**: 79 unit + 39 integration on the isolated test DB (incl. 8 sign-in-only end-to-end tests) |
| Backend lint and types (`ruff`, `mypy --strict`) | clean |
| Frontend tests, lint, typecheck, build | 27 passed; clean; builds |
| `scripts/smoke-test.sh` | **31/31 passed** |
| Live Steam Store ingestion via the worker (no key needed) | Stardew Valley, Hades, RimWorld and Factorio ingested; 446 tags and 13 categories; e.g. Factorio → automation 1.00, base-building 0.94, resource-management 0.85, each with Steam-tag evidence |
| Real Steam sign-in in a browser | ✅ the owner signed in at localhost:3000; Steam confirmed the assertion server-side; user and session created |
| Key-free endpoints, live | ✅ store search (e.g. "hollow knight" → Hollow Knight, Silksong), public profile XML (name, avatar, visibility) |
| Real public library import | ✅ 2026-11-15: the owner's library, 539 games (265 played), 529,690 min total, 2,306 min in 2 weeks, in ~10 s; metadata for 513 games (25 delisted); achievements for the 10 most recent; all signed-in pages render it |

Defects found and fixed during this stage:
- httpx logged full request URLs, which would have written the Steam API key to the logs. Fixed and covered by a test.
- Steam app type 0 (game) was parsed as unknown.
- Celery CLI defaults silenced all worker application logs.
- Lazy `shared_task` binding was fragile; tasks are now bound explicitly.
- A blank `STEAM_WEB_API_KEY=` counted as configured.
- A swallowed `cookies()` prerender interruption risked baking signed-out content into the static shell.
- An 82-character constraint name would have been silently truncated by PostgreSQL.
- Hostile XML (entity expansion) raised an uncaught defusedxml error; it's now a contained provider error.
- Slotted dataclasses were serialised via `__dict__`; replaced with `asdict`.

### Acceptance criteria

| Criterion | Status |
|---|---|
| Steam authentication works | ✅ live in a browser and in tests |
| User identity is verified | ✅ server-side `check_authentication` + 15 rejection-path tests |
| Private game details are handled correctly | ✅ tests; live account confirmed `accessible` |
| A real public library can be imported | ✅ live, 539 games (ADR-0015) |
| Library data is stored persistently | ✅ PostgreSQL volume (Stage 1 persistence check) |
| Duplicate games are prevented | ✅ unique external ids, advisory lock, concurrent test, merge |
| Playtime snapshots are recorded | ✅ 539 snapshots from the live import |
| Game features can be mapped and queried | ✅ live Steam data and API |
| Provider failures do not break Steam integration | ✅ store outage test; imports independent of metadata |
| Tests cover auth, privacy failures, import, duplicates | ✅ |

## Notes for the next stage

- **Automatic import is the product path (ADR-0015).** Playtime, recency and ownership come from Steam. Ratings (`user_feedback`) are an extra signal. Manual entries (no-key fallback) have NULL playtime, so code must still never treat NULL as 0.

- Use `game_feature_values` for content scoring, rolling hierarchies up with MAX. Weight groups come from `feature_categories.scoring_group`. Unknown means no row.
- Recent playtime is the 2-week value. 30-day recency must be built from `playtime_snapshots` (OPEN_QUESTIONS #3).
- The UI must say "Match", not a percentage, until scores are calibrated (`ScoreKind`).
- Open items: #15 Steam data terms (legal), #17 stale-queued-run reaper, privacy UI (opt-outs, export, deletion), prices for "Games I Should Buy".
