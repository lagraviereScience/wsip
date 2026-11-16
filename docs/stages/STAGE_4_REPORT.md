# Stage 4 report: behaviour tracking and collective recommendation learning

Prompt: [docs/spec/prompts/PROMPT_4_BEHAVIOUR_AND_COLLABORATIVE_LEARNING.md](../spec/prompts/PROMPT_4_BEHAVIOUR_AND_COLLABORATIVE_LEARNING.md) · Date: 2026-11-15

Design:
- [docs/BEHAVIOUR.md](../BEHAVIOUR.md): events, feedback, profile adaptation, satisfaction question
- [docs/COLLABORATIVE.md](../COLLABORATIVE.md): signals, models, pipeline, serving
- [docs/PRIVACY.md](../PRIVACY.md): controls, isolation, training data, deletion
- [benchmarks/CF_BENCHMARK_SYNTHETIC.md](../benchmarks/CF_BENCHMARK_SYNTHETIC.md)
- ADR-0009 (amended), ADR-0017, ADR-0018

## Decision taken with the project owner
**LightFM was skipped.** Its 2023 release and its pinned source don't build on Python 3.12.
Asked to choose between a community fork, patching the official source, or skipping it,
the owner chose to skip it (OPEN_QUESTIONS #24). The benchmark compares `implicit` ALS and
BPR, each pure and **hybrid** (game features as pseudo-users), against popularity and
content baselines.

## What was built

### A. Event system
- **`behaviour_events`**, append-only and enforced by a database trigger, covering:
  - exposure and navigation: impressions, clicks, game page views, Steam Store visits;
  - feedback: like, dislike, favourite, save for later, not interested (with reason),
    not my type, already played (each with on/off for undo);
  - satisfaction ratings, question actions, playtime changes, manual preference and
    exclusion changes.
- Each event stores the recommendation run, category, visible position, **model version**
  and surface.
- **Impressions are real visibility**: at least 50% of the card on screen for 1 s, once per
  page view. Clicks are separate events on the card's title or artwork.
- **Duplicates**: browser events carry idempotency keys, unique per user. Retries and
  in-batch repeats are counted and skipped.
- Exposure context from the browser is checked against the user's own runs. Category and
  model version always come from the stored run.
- **Playtime changes**: each library sync records growth since the previous sync, linked to
  the last recommendation exposure within 90 days. The first import is not counted as growth.

### B. Feedback interface
- Every recommendation card has Like, Dislike, Favourite and Save, plus a **More** menu:
  - Not interested, which asks why: too expensive, not right now, own it elsewhere, just
    not interested;
  - Not my type;
  - Already played, with an optional "Did you enjoy it?".
- Every control toggles, so pressing again undoes it. A hidden card collapses to an
  **Undo** row.
- **Game page** `/games/{id}`: live Match with reasons and points, feedback controls,
  Steam link. Cards link to it.
- **Post-play question** on the dashboard, asked only after **2 h of play since we
  recommended the game**:
  - one question at a time, one new question a week at most;
  - "Not now" snoozes it for 2 weeks; "Don't ask" stops it; at most twice per game.
- **Profile → Your game feedback** lists every game with feedback, with filters and the
  same controls. **Dashboard → Saved for later** lists saved games.

### C. Individual preference adaptation
- **Feedback is a fourth profile signal** (`content-v2`), kept separate from ratings,
  historical playtime and recent playtime.
- Values: favourite +1, like +0.6, save +0.3, dislike −0.6, not my type −1. Weight 0.8:
  below ratings (1.0), above playtime (0.5).
- "Not interested" and "already played" add no taste evidence, so price is never
  mistaken for gameplay.
- **Manual preferences remain authoritative**: they replace inferred values, and feedback
  never writes them.
- Profiles are rebuilt from the *current* feedback state, so **undo fully reverts** while
  the event log keeps the history. Each change queues a rebuild after a 5 s debounce.
- **Explicit negatives are respected**: disliked, dismissed, already played and
  negatively rated games are removed from candidates and hidden from stored lists at once.

### D. Collaborative filtering
- **Signals are typed and weighted** (docs/COLLABORATIVE.md §1):
  - ratings decide on their own;
  - explicit negatives override positives;
  - interest, engagement (log playtime) and weak signals (clicks, page views, store
    visits, capped at 1) add up;
  - ownership without play and exposure without interaction are **not** positives;
  - price or timing rejections carry no signal.
- **Models**: popularity, content, ALS, hybrid ALS, BPR, hybrid BPR (`implicit` 0.7,
  single-threaded, seeded).
- **Daily pipeline** (04:35 UTC, `training` queue):
  1. opted-in users only, pseudonymised;
  2. chronological and cold-item splits;
  3. six models evaluated, every metric stored;
  4. gates: minimum data, 1.05 × popularity on NDCG@5, no rise in rejected games, not
     worse than the deployed model;
  5. deploy, or keep the current model;
  6. rollback with `python -m app.cli rollback-cf`.
- **Serving**:
  - users are folded in from their own current data (artifacts hold no user rows);
  - the top 100 collaborative games join the unowned candidates;
  - the collaborative percentile is blended into Match (weight up to 0.3, scaled by the
    user's evidence);
  - runs record `content-v2+<version>` and `model_version_id`.
- **Recommends games outside the library**: owned games are never candidates in the
  unowned list (tested with a deployed model).

### E. Cold start
- **New users** get content-based recommendations: a brand-new account gets a full
  unowned list with honest "we don't know your taste yet" reasons (tested and checked
  live).
- Collaborative scores need at least 3 positive interactions with modelled games.
- **New games**: games unknown to the model are ranked by metadata alone. Hybrid ALS
  gives games with tags but no interactions metadata-based factors.
- **No fabricated collective knowledge**: nothing collaborative is used, and no
  "players like you" text appears, until a model trained on real players passes its gates.
  Today: 1 player, 265 positive interactions. Training reports "Not enough data … (need 25
  and 500)".

### F. Privacy
- **Training opt-out** in Settings. Opted-out data never enters a dataset; the user's own
  recommendations still work.
- **Isolation**: every endpoint acts on the signed-in user only, and a foreign run id is
  ignored (tested with two signed-in users).
- **Pseudonymised datasets**: HMAC with a one-off salt, never stored or written to disk.
- **Deletion**: `DELETE /api/me`, with a typed confirmation in the UI, removes every row
  tied to the account (all foreign keys cascade), clears the session and Redis keys, and
  records a timestamp-only deletion marker that triggers a retrain.
- Retired model artifacts are deleted after 30 days. No machine-unlearning claim is made
  (docs/PRIVACY.md).
- **Export**: `GET /api/me/export`, a JSON file of 17 sections.
- **Daily-sync toggle** now works.
- Legal items to review before launch are listed (OPEN_QUESTIONS #25).

## Benchmark (synthetic players, 3 seeds)

| Algorithm | NDCG@5 known games | NDCG@5 new games | Negative rate@5 |
|---|---:|---:|---:|
| popularity | 0.080 | 0.030 | 0.020 |
| content | 0.061 | **0.287** | 0.001 |
| ALS | 0.155 | 0.030 | 0.004 |
| **hybrid ALS** | **0.160** | 0.275 | 0.005 |
| BPR | 0.137 | 0.030 | 0.012 |
| hybrid BPR | 0.133 | 0.106 | 0.009 |

Hybrid ALS is the best all-rounder: about 2× popularity on known games, and nearly content-level on brand-new
games where pure collaborative filtering knows nothing. These are **synthetic** players
with planted structure. They show the models learn; they do not predict real quality. Full
table and caveats: [benchmarks/CF_BENCHMARK_SYNTHETIC.md](../benchmarks/CF_BENCHMARK_SYNTHETIC.md).

## Verification

| Check | Result |
|---|---|
| Backend tests in Docker | **204 passed**: 142 unit + 62 integration |
| New unit tests (19) | Feedback in profiles (priority, neutral kinds, undo, weights), signal interpretation, pseudonyms, confidence encoding, fold-in = `implicit`'s solver, models learn the planted taste, only metadata-aware models handle new games, determinism, no leakage in splits, artifacts (round trip, checksum, BPR bias), blending |
| New integration tests (13) | Events stored once, impressions ≠ clicks, foreign context dropped, append-only trigger, feedback toggle/undo/history, feedback → profile with manual precedence, explicit negatives, satisfaction-question policy, playtime attribution on sync, training skipped without data, training on a 90-player population (opted-out excluded, pseudonyms only, all metrics stored, gates, rerun skipped, retrain after deletion), serving blend and cold start, privacy (opt-out, export, deletion), two-user isolation |
| Migration 0005 | upgrade → downgrade → upgrade, and `alembic check` reports no drift |
| Backend lint and types | ruff and mypy --strict clean (99 files) |
| Frontend | **49 tests** (13 new), typecheck, lint and production build clean |
| Smoke test | **38/38** (5 new checks) |
| Secret scan | Steam key and owner email in no repository file |

### Live checks on the owner's data (2026-11-15)

| | |
|---|---|
| Training run | `skipped`: "1 players with signals (need 25) and 265 positive interactions (need 500)" |
| Rebuild | Profile with 149 features; owned 60, unowned 60, all `content-v2`, no model |
| Owner's lists (read-only session) | Feedback state on every item, no collaborative score, game page Match for Gray Zone Warfare 57.6 (high), no events or feedback on the account |
| Write paths on a throwaway account | Events 2 accepted / 1 duplicate, retry 0 / 3; like; "not interested (price)" hid the game; undo; rating; 4 history entries; export of 17 sections; delete without confirmation 422; delete 204 with cookie cleared, then `/api/me` 401; **no rows left** |

Temporary sessions, the throwaway account and its deletion marker were removed afterwards.

### Defects found and fixed during the stage
- The slim runtime image lacked `libgomp1`, which `implicit` needs. Collaborative
  training would have crashed in production; it is now installed in the Dockerfile.
- `recommendation_runs.algorithm` (32 characters) could not hold
  `content-v2+cf-…-hybrid_bpr`. It is widened to 64 in migration 0005.
- The game page (a dynamic route) failed the production build because the navigation read
  the URL outside `<Suspense>`. The navigation now has a static fallback.
- Integration tests left model-registry rows between tests. Those tables are now
  truncated.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Events are stored reliably | ✅ append-only table with trigger, server-side events in the same transaction as the state change, batched browser delivery with keepalive |
| Duplicate event submissions are handled | ✅ unique idempotency keys per user; in-batch and retry duplicates counted and skipped (tests and live) |
| Impressions are distinct from clicks | ✅ separate types; an impression needs 50% visibility for 1 s; clicks only on title or artwork (tests and live) |
| Feedback affects individual profiles | ✅ fourth profile signal; undo reverts; manual preferences stay authoritative (unit and integration tests) |
| Collaborative models train on valid data | ✅ typed signals, opted-in users only, pseudonymised, chronological evaluation, gated deployment (90-player integration test) |
| New users still receive recommendations | ✅ content-based list for a brand-new account (test and live) |
| Explicit negatives are respected | ✅ hard filter in every category and immediate hiding; negative training signal; price rejections neutral |
| Global model training excludes users who opted out | ✅ eligibility query, dataset statistics and pseudonym count checked in tests; the Settings toggle works |

## Not verified
- **I did not click through the new UI in a real browser.** It is covered by component
  tests (feedback controls, Undo, impressions with a mocked IntersectionObserver,
  satisfaction question, privacy controls) and by server-rendered HTML checks of every
  page.
- **No collaborative model has been trained on real players** (there is one). Deployment
  and serving were exercised only on the synthetic population in the test database.
- The satisfaction question can't appear for the owner until they play a recommended game
  for 2 hours *after* this stage (it needs `playtime_change` events after an exposure).

## Notes for the next stage
- **LightGBM satisfaction model** (spec §18): needs post-play ratings, which now have a
  collection path. It can reuse the model registry with a new `kind`.
- **Calibration** (OPEN_QUESTIONS #21) and **satisfaction-rate evaluation with feedback
  coverage** (spec §25) become possible once ratings accumulate.
- Open items:
  - #24 LightFM (deferred);
  - #25 training consent (legal);
  - #26 event retention and partitioning;
  - #27 question thresholds;
  - #28 deployment gates;
  - #15 Steam data terms;
  - #17 stale-run reaper.
- Card pages grew to about 680 KB uncompressed for 24 cards (feedback controls), up from
  about 580 KB.
