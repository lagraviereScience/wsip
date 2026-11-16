# Stage 3 report: gamer profiling and initial recommendation engine

Prompt: [docs/spec/prompts/PROMPT_3_PROFILING_AND_RECOMMENDATIONS.md](../spec/prompts/PROMPT_3_PROFILING_AND_RECOMMENDATIONS.md) · Date: 2026-11-15

Design: [ADR-0016](../adr/0016-content-based-engine.md) · Formulas and parameters: [docs/RECOMMENDATIONS.md](../RECOMMENDATIONS.md)

## What was built

### A. Game feature vectors
- Sparse canonical vectors with values and metadata confidence in 0…1. Unknown is absent, never 0.
- Multi-source merge: confidence-weighted value and noisy-or confidence.
- Within-category shares and hierarchical roll-up, so parents and children are never double counted.

### B. Player preference vectors
- Three separate signals per feature:
  - **satisfaction** from explicit ratings (the primary label);
  - **historical behaviour**: lift of log-scaled lifetime playtime over catalogue prevalence;
  - **recent behaviour**: two-week playtime and decayed recency.
- Behaviour is capped at −0.5 and at 0.6 confidence, so playtime is never read as satisfaction.
- Playtime per canonical feature, distributed within categories.
- Strength (−1…1) and confidence (0…1) are stored separately.
- Manual values override inferred ones at confidence 1. Exclusions are hard filters covering descendants.
- Update history:
  - `profile_runs` stores the full parameters of each computation;
  - `user_feature_preference_history` stores values that changed;
  - `user_preference_events` logs manual changes.

### C. Content-based compatibility
- Spec §16 group weights.
- Resolution to the most specific usable preference on each lineage.
- Confidence-weighted group scores with an evidence-reliability shrink.
- Renormalisation over groups that have metadata, so missing metadata is never a penalty.
- **Exact additive decomposition**: each feature's points sum to Match − 50.
- Outputs: overall score, group scores, contributions, metadata confidence, preference coverage and recommendation confidence.

### D. Recommendation generation
Candidate generation and ranking are separate steps.

| Category | What it does |
|---|---|
| **Owned** | Library games, minus games played in the last 14 days and games with 100 h or more. `0.85 · Match + 0.15 · Backlog`, using the spec §20.1 backlog formula |
| **Unowned** | Catalogue games neither owned nor rated, with at least 200 reviews. Ranked by Match, with "Similar to your favourite" detection. Price, discount and reviews are shown separately. Filters: price, free-to-play, reviews, release years, players |
| **Trending** | Players are sampled from `GetNumberOfCurrentPlayers` every 2 hours and aggregated daily. Spec growth and acceleration are converted to percentiles. Scores appear **only** after 42 days of data that passes the quality checks; until then the run is `unavailable` with an explanatory note. A separate "Popular right now" list is labelled as absolute popularity, not a trend |

Discovery widens the catalogue using Valve's public store API only:
- per user: `IStoreQueryService/Query` with the player's liked tags;
- daily: Steam's most-played chart and weekly top sellers.

### E. Explanations
Template sentences generated from contributions and library facts (`feature_match`, `recent_interest`, `manual_preference`, `feature_conflict`, `broad_match`, `similar_to_favourite`, `never_played`, `barely_played`, `dormant`, `trend_growth`). Each feature-based reason carries its feature slug and points. No language model is used.

### F. Interface
- **Dashboard**: top pick, profile summary, recent activity, backlog and trending status.
- **Gamer profile**: stats, likes, dislikes, singleplayer/multiplayer balance, excluded tags, recent vs lifetime, most influential games, and the **preference editor** (Hate…Love, Exclude, Reset, taxonomy search including synonyms).
- **Games I Should Play**, **Games I Should Buy** (with filters) and **Trending**: real lists with a "Why this score" breakdown on every card, a building state while the first run is computed, and a rebuild button.
- Signed-in users never see sample data.

### Background jobs
- `refresh_recommendations` runs after each import, after preference changes (5 s debounce, no discovery) and on demand (60 s cooldown).
- Scheduled jobs: `discover_global_candidates` (daily), `sample_player_counts` (every 2 h) and `aggregate_player_counts` (daily).
- New worker queues: `recommendations` and `trends`. Concurrency is now 3.

## Verification

| Check | Result |
|---|---|
| Backend tests in Docker | **172 passed**: 123 unit + 49 integration |
| Engine unit tests on synthetic users and games | 37, covering all six required cases: strong genre, strong mechanic, contradictory preferences, excluded tags, incomplete metadata and unknown preferences. Also hierarchy, determinism, exact decomposition, the playtime ≠ satisfaction rule, trends and percentiles |
| Integration (test DB, least-privilege role) | 10 new tests: profile from library, history only on change, owned/unowned filtering, traceable explanations, exclusions, trending unavailable vs computed, aggregation, and the API (pending → ready, filters, profile, manual preferences, 404/422/403 cases) |
| Backend lint and types | ruff and mypy --strict clean (83 files) |
| Frontend | 36 tests (8 new), typecheck, lint and production build |
| Smoke test | **33/33** (2 new checks) |
| Live store endpoints (2026-11-15) | Query by tag, most played, top sellers, current players and discounted prices all verified; small real responses saved as fixtures |

### On the owner's real Steam data

| | |
|---|---|
| Profile input | 539 owned games, 511 with metadata, 265 played |
| Preferences inferred | 149 features, each with value, confidence, historical, recent and satisfaction components; profile confidence 1.0 |
| Strongest inferred likes | Vehicular combat, Sports, Racing, Online co-op, PvE, Fishing and hunting, Combat, Procedural generation |
| Strongest inferred dislikes | Platforming, Puzzle, Cyberpunk, Short games (all at the −0.5 behaviour cap) |
| Catalogue after discovery | 767 games, 786 with features, 270 prices |
| Owned list | 60 ranked from 539. 18 heavily played or currently played games were left out. Top picks are unplayed or barely played, e.g. Songs of Conquest and THE FINALS |
| Unowned list | 60 ranked from 267 candidates, e.g. Warhammer 40,000: Darktide, Gray Zone Warfare ("Similar to Arma 3"), PAYDAY 3. All 60 have at least one traceable reason |
| Trending | `unavailable`: 400 games sampled since 2026-11-15; scores expected from about 2026-12-27 |
| Full rebuild time | About 22 s with discovery, about 5 s without |

Defects found and fixed during the stage:
- An unclosed test session blocked table truncation, hanging the test suite.
- The preference editor lost a row found by synonym after saving it (caught by a new test).
- "Played only 0.0 h": short playtimes now show in minutes.
- "Current interest" fired too often; it now needs recent ≥ 0.6, a gain of at least 0.25 over lifetime and recent confidence ≥ 0.3.
- Recommendations made only of small matches had no reason; `broad_match` now names the top contributing features.
- A dict-typed `RECOMMENDER_OVERRIDES` would fail on an empty compose value; it is now a JSON string validated at startup.
- Full list pages were 1.4 MB; they now render the top 24 by default (about 580 KB, uncompressed), with "Show all".

### Acceptance criteria

| Criterion | Status |
|---|---|
| Real Steam data generates a gamer profile | ✅ 149 features from the owner's 539-game library |
| The profile contains numerical preferences and confidence | ✅ value −1…1 and confidence 0…1, stored separately, plus components |
| Users can manually change preferences | ✅ editor and `PUT`/`DELETE /api/me/preferences/{slug}`; manual values override inferred ones and are logged |
| Excluded tags are respected | ✅ hard filter before ranking in all categories, descendants included (unit and integration tests) |
| All three recommendation categories exist | ✅ owned and unowned populated; trending implemented with an honest unavailable state until 42 days of data |
| Owned and unowned filtering is correct | ✅ integration test: no owned or rated game in unowned; owned contains only library games |
| Content scoring is deterministic and tested | ✅ order-independence, determinism and exact decomposition tests |
| Recommendation explanations are traceable to actual features | ✅ every feature reason carries its slug and points; integration test checks reasons against contributions; UI shows the breakdown |
| No fabricated game data is shown as real data | ✅ signed-in pages contain only real data; trend scores are withheld until real history exists; "Popular right now" is labelled as not a trend; unknown values are shown as unknown |

## Not verified
- I did not view the new pages in a browser myself. I checked server-rendered HTML for every page with a temporary 15-minute session, deleted afterwards, plus component tests. The preference editor's live save → rebuild loop was tested through the API and component tests, not by clicking in a real browser.
- Trend scoring with real Steam data cannot be checked before about 2026-12-27; it is covered by integration tests with synthetic 42-day series.

## Notes for the next stage
- `user_feedback` (ratings) already feeds the satisfaction component. Post-play feedback and `behaviour_events` (spec §21) will strengthen it, and are the labels for calibrating "Match" (OPEN_QUESTIONS #21).
- Collaborative filtering should become another candidate source alongside content, similarity and discovery, and its score another input to ranking (spec §19). `recommendation_items.candidate_sources` already records provenance.
- Parameters are versioned (`content-v1`). Evaluating weights needs held-out satisfaction labels (spec §25).
- Open items: #15 Steam data terms (legal), #17 stale-queued-run reaper, #19–#23 (new), privacy UI (export and deletion, which should cover the new tables).
