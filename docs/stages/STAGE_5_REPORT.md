# Stage 5 report: satisfaction prediction and daily model training

Prompt: [docs/spec/prompts/PROMPT_5_SATISFACTION_AND_DAILY_TRAINING.md](../spec/prompts/PROMPT_5_SATISFACTION_AND_DAILY_TRAINING.md) · Date: 2026-11-15

Design: [docs/SATISFACTION.md](../SATISFACTION.md) · [ADR-0019](../adr/0019-satisfaction-model.md) ·
Sample report (synthetic): [benchmarks/SATISFACTION_SAMPLE_REPORT.md](../benchmarks/SATISFACTION_SAMPLE_REPORT.md)

## Current state on real data
The whole pipeline runs daily and on demand. **No model is deployed yet**, because
there isn't enough real data:

| Model | Have | Needed |
|---|---|---|
| Collaborative | 1 player, 265 positive interactions | 25 players, 500 interactions |
| Satisfaction | 4 labels (your "dislike" reactions) | 200 labels |

Until then:
- recommendations are ranked exactly as before, by Match;
- cards say "Match", never a percentage;
- each run still writes its evaluation report and keeps the previous state.

## What was built

### A. Satisfaction model
- **Target**: explicit satisfaction.
  - Ratings: Liked or Loved = satisfied; Neutral, Disliked or Hated = not; weight 1.0.
  - For unrated games: favourite (0.5), dislike (0.5) and not my type (0.3).
- **Never labels**:
  - clicks, page views, store visits and impressions;
  - likes and saves;
  - "not interested";
  - unrated "already played";
  - playtime;
  - no interaction.

  All of these are counted in each report.
- **LightGBM binary**: CPU, single thread, fixed seed, early stopping on the end of the
  training window.
- **Compared against** a base rate and a **content-only logistic baseline** (Match →
  probability).
- **Investigated and reported**, not deployed: **ordinal** regression on ratings (MAE,
  Spearman) and a **LambdaRank** ranker grouped by player (NDCG@5).
- **Calibration** is fitted on a separate later window: isotonic with ≥ 300 rows,
  otherwise Platt. "Predicted enjoyment N%" appears only for a deployed model that
  passed the **ECE ≤ 0.08** gate.

### B. Features without leakage (82, schema `sat-v1`)
- Every training row uses the player's state **just before the label, with the
  labelled game removed**: earlier ratings and reactions, playtime snapshots of the
  time, earlier exposures, and manual preferences replayed from their log.
- Serving runs the same code at "now".
- The **collaborative feature is cross-fitted**: item factors from other players and
  earlier data; the player folded in without the labelled game.
- Groups: content compatibility (on the as-of profile), collaborative percentile,
  category, exposure context, game (popularity, age, tag vector), similar players
  (others' earlier ratings of the game), and player (activity, rating history,
  preference vector).

### C. Category ranking models
| Category | Score |
|---|---|
| Owned | 0.85 · satisfaction + 0.15 · backlog |
| Unowned | satisfaction |
| Trending | 0.8 · satisfaction + 0.2 · trend |

- "Satisfaction" is the calibrated prediction × 100 when deployed, otherwise Match.
- Weights are configurable; satisfaction must keep at least half of each category's
  weight (checked at startup).
- **Per-category safety check**: where the model ranks a category worse than content
  in testing, that category keeps Match.

### D. Daily pipeline
- `train_models` runs at 04:35 UTC on the `training` queue: the collaborative stage,
  then the satisfaction stage.
- Steps: prepare (opted-in, pseudonymised) → validate → features → train → evaluate
  (time-based 70/15/15 split) → compare with production → register → deploy only if
  every gate passes → keep for rollback.
- Each stage is isolated. A crash is recorded as a failed run, and the next stage and
  the serving models are unaffected.
- **Manual trigger by administrators**: `docker compose exec worker python -m app.cli
  train` (`--only`, `--queue`). There is no admin web endpoint, as spec §35 requires.

### E. Versioning
`model_versions` stores, per version:
- id and kind, and the training timestamp;
- dataset statistics, hyperparameters (with the calibration method) and the
  **feature schema version**;
- metrics, artifact path and SHA-256, and status.

JSON artifacts (no pickles) live on the persistent `models` volume. Every deploy and
rollback is logged (`app.cli models`, `app.cli rollback <version>`).

### F. Monitoring and reports
- `monitor_models` runs daily at 05:45 UTC (and on `app.cli monitor`) over a 30-day
  window. It stores:
  - satisfaction rate **with feedback coverage** and a selection-bias note;
  - negative feedback rate;
  - production calibration;
  - online NDCG@5 and precision@5;
  - coverage and diversity;
  - training failures;
  - **drift** (PSI of predictions, Match and the collaborative percentile).

  Alerts fire on failures, miscalibration and drift. Metrics without data are empty,
  not zero.
- **Evaluation reports** for every training run are stored as JSON in
  `training_runs.report` and as Markdown in `<models_dir>/reports/`.

## Sample run (synthetic players, test database)
One full pipeline run on 200 simulated players, from the
[sample report](../benchmarks/SATISFACTION_SAMPLE_REPORT.md):

| Model (test window, 368 labels) | AUC | Log loss | ECE |
|---|---:|---:|---:|
| Base rate | 0.500 | 0.678 | 0.016 |
| Content baseline | 0.679 | 0.636 | 0.048 |
| **LightGBM, calibrated** | **0.803** | **0.527** | 0.069 |

- Ranking within players (NDCG@5): LightGBM 0.95, content 0.90.
- All gates passed. The per-category check kept **unowned and trending on Match**
  because content was better there; the model is used for owned games.
- Simulated data shows the system works end to end; it does not predict real quality.

## Verification

| Check | Result |
|---|---|
| Backend tests in Docker | **223 passed**: 155 unit + 68 integration |
| New unit tests (13) | Label rules (clicks, likes, saves, playtime and no interaction never labels; neutral is not satisfied), as-of state (target and future excluded, snapshots, manual replay, ownership kept), feature rows independent of the label, calibration (isotonic, Platt), training beats content, determinism, artifact round trip and checksum, category weights and validation, per-category check, reports, schedule, PSI |
| New integration tests (6) | Full daily pipeline trains, evaluates, registers and deploys with stored reports and opted-out players excluded; serving with calibrated predictions and category weights, plus newcomers; insufficient data keeps the deployed model; a training crash and an unreadable artifact never stop recommendations; rollback; 900 click/page/store events don't change labels; monitoring report stored with every metric |
| Migration 0006 | upgrade → downgrade → upgrade, and `alembic check` reports no drift |
| Backend lint and types | ruff and mypy --strict clean (109 files) |
| Frontend | **50 tests** (1 new), typecheck, lint and build clean |
| Smoke test | 38/38 |
| No GPU | LightGBM and implicit run on CPU in the standard image (`libgomp1` only) |
| Live (your data) | `app.cli train` and the queued variant run; both stages skip for lack of data and write reports; `app.cli models`, `report` and `monitor` work; monitoring stored; your lists unchanged (`content-v2`, no predictions) |
| Secret scan | Steam key and owner email in no repository file |

### Defects found and fixed during the stage
- **Train/serve skew on ownership.** Hiding the labelled game in the as-of view also
  hid that the player owned it. Training saw "owned = 0" for every row, while
  serving saw 1 for owned games. Found through the sample report, where every test
  row was "unowned". Ownership is now kept (it is known at prediction time), with
  unit and integration tests.
- **Online NDCG counted undone feedback.** A like that was later removed counted as a
  positive outcome. Monitoring now uses the current feedback state.
- **Non-reproducible collaborative training** (from Stage 4). Players were ordered by
  per-run random pseudonyms, so the same data trained slightly different models, and
  a test was flaky near the gate. They are now ordered by a fingerprint of their
  signals.
- Two frontend tests raced the in-flight save (buttons are disabled while saving).
  The tests now wait.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Daily training can be scheduled | ✅ `train-models` at 04:35 and `monitor-models` at 05:45 on the `training` queue (unit test on the schedule) |
| Training can also be triggered manually by administrators | ✅ `python -m app.cli train` (in-process or `--queue`); checked live |
| Models are versioned | ✅ id, timestamp, dataset, hyperparameters, feature schema, metrics, artifact and SHA-256, status, deployment history |
| Models are evaluated before deployment | ✅ time-based split, baselines, calibration, gates; the deployed model is exactly the evaluated pair |
| Rollback works | ✅ `app.cli rollback <version>` (integration test: deploy, deploy, rollback; serving switches back) |
| Users continue receiving recommendations if training fails | ✅ crash, unreadable artifact and schema mismatch all fall back to Match (integration test) |
| The satisfaction model is not trained on unqualified click events | ✅ labels only from ratings and weighted explicit reactions; 900 added click/page/store events left the label count unchanged |
| The system works without a GPU | ✅ CPU-only LightGBM and implicit, single-threaded |
| Evaluation reports are generated and stored | ✅ JSON in `training_runs.report` and Markdown under `<models_dir>/reports/` for every run, including skipped and failed ones |

## Not verified
- **No model has been trained on real players**: there is one player with no ratings.
  Deployment, serving and monitoring with a deployed model were exercised only on
  simulated players in the test database.
- **I didn't see "Predicted enjoyment" in a browser.** It is covered by a component
  test, and the cards fall back to "Match" until a model is deployed.

## Notes for the next stage
- Open questions:
  - #29 satisfaction gates;
  - #30 reaction label weights;
  - #31 admin access (CLI for now);
  - #32 monitoring alerts are stored but not delivered.
- The next stage could deliver alerts, show a model status page to admins, and add
  A/B testing once traffic allows (spec §25).
