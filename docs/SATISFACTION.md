# Satisfaction prediction, daily training and monitoring (Stage 5)

Turns collected feedback into a calibrated prediction of whether a player will
enjoy a game (spec §18, §24, §25; Prompt 5). Decisions: [ADR-0019](adr/0019-satisfaction-model.md).

| Part | Code (`backend/app/`) |
|---|---|
| Point-in-time history | `machine_learning/features/history.py` |
| Features (schema `sat-v1`) | `machine_learning/features/builder.py` |
| Labels | `machine_learning/satisfaction/labels.py` |
| Dataset, training, gates | `machine_learning/satisfaction/training.py` |
| Model, calibration, metrics, artifacts | `machine_learning/satisfaction/model.py` |
| Pipeline stage | `machine_learning/training/satisfaction_pipeline.py` |
| Daily orchestration | `machine_learning/training/daily.py`, task `train_models` |
| Reports | `machine_learning/reports.py` |
| Monitoring | `machine_learning/monitoring.py`, task `monitor_models` |
| Serving | `recommendations/ranking/satisfaction.py` |
| Category ranking | `recommendations/ranking/scores.py` (`category_score`) |

## Current state (2026-11-15)

The pipeline runs, but **no satisfaction model is deployed**.

| Data | Have | Needed |
|---|---:|---:|
| Labels | 4 (all "dislike" reactions) | 200 |
| Players | 1 | — |

Until a model passes its gates:
- recommendations are ranked by Match, exactly as before;
- cards show "Match", never a percentage.

## 1. Labels: explicit satisfaction only

| Source | Label | Weight |
|---|---|---:|
| Rating Loved or Liked | satisfied | 1.0 |
| Rating Neutral | not satisfied | 1.0 |
| Rating Disliked or Hated | not satisfied | 1.0 |
| Favourite (game not rated) | satisfied | 0.5 |
| Dislike (game not rated) | not satisfied | 0.5 |
| Not my type (game not rated) | not satisfied | 0.3 |

**Never labels**, though they are counted in every report:
- clicks, game page views, store visits and impressions;
- likes and saves (interest, not satisfaction);
- "not interested" (price or timing);
- "already played" without a rating;
- playtime of any amount;
- no interaction (unknown, not dissatisfaction).

A test adds 900 click, page-view and store events to unlabelled games and checks
that the label count does not change.

## 2. Features without leakage

Every training row is built from what was known **before** the label, with the
labelled game removed (`as_of`):
- **Ratings and reactions**: only those changed earlier.
- **Library playtime**: from the latest snapshot at the time.
- **Exposures**: only earlier ones.
- **Manual preferences**: replayed from their change log.
- **The labelled game's own** rating, reactions and playtime are never features.

Serving uses the same code with "now" and no exclusion, so training and serving
can't drift apart. A test flips a label and checks that the feature row is
identical.

| Group | Features |
|---|---|
| Content compatibility | Match, confidence, metadata confidence, preference coverage, 5 group scores, positive and negative points, all from the as-of profile |
| Collaborative | Percentile of the game for the player. In training it is **cross-fitted**: hybrid ALS on the *other* players (3 folds), using data before the test window, with the player folded in from their earlier signals minus the labelled game. In serving it comes from the deployed collaborative model. NaN when unavailable |
| Category | Owned at the time; owned, unowned or trending context |
| Exposure context | Shown before, impressions, best position, clicked before |
| Game | Review count (log), positive %, age, free; rolled shares of the 24 most common tags (game vector) |
| Similar players | Other opted-in players' ratings of the game **before** t: count and shrunk positive rate |
| Player | Library size, lifetime and recent hours, prior ratings (count, shrunk mean and positive rate), feedback count, profile confidence, preference vector on the same 24 tags |

There are 82 features. Not used: per-neighbour "similar player" weighting (the
collaborative percentile covers it) and price, which is shown but never ranked
(spec §20.2).

## 3. Training and evaluation

**Time-based split** by label time: 70% train, 15% calibration, 15% test.

Models, all on the same split:

| Model | Role |
|---|---|
| Base rate | Baseline |
| **Content logistic** | Match → probability. The baseline to beat |
| **LightGBM binary** | Deployable: 15 leaves, depth 5, learning rate 0.05, early stopping on the end of the training window, single thread, fixed seed, CPU only |
| Calibration | Isotonic with ≥ 300 calibration rows, otherwise Platt sigmoid, fitted on the calibration window |
| LambdaRank (grouped by player) | Investigated and reported, not deployed |
| Ordinal regression on ratings | Investigated and reported (MAE, Spearman), not deployed |

**Metrics**:
- AUC, log loss, Brier score, ECE and a calibration table (predicted vs observed per bin);
- NDCG@5 within each player's test labels;
- per-category AUC (owned vs not owned);
- top features by gain.

**Gates** (all must pass to deploy; settings in brackets):
- at least 40 test rows, with at least 10 of each class (`SAT_MIN_TEST_ROWS`, `SAT_MIN_CLASS_ROWS`);
- calibrated LightGBM AUC ≥ content AUC + 0.01, and log loss ≤ content log loss (`SAT_MIN_AUC_LIFT`);
- **ECE ≤ 0.08** (`SAT_MAX_ECE`), before it may be shown as a percentage;
- AUC ≥ 0.98 × the deployed model's recorded AUC (`SAT_DEPLOYED_TOLERANCE`).

Training is skipped below **200 labels** (`SAT_MIN_LABELS`). The previous model is then kept.

**Per-category check.** Where the model's AUC on a category's test rows is more
than 0.01 below the content baseline's, with at least 30 rows, that category keeps
ranking on Match. Trending follows unowned, since trending games are not owned. The
decision is stored in the model (`params.categories`) and in the report. At least one
category must use the model for it to deploy.

Example: in the [sample report](benchmarks/SATISFACTION_SAMPLE_REPORT.md)
(synthetic), the model beat content overall (AUC 0.80 vs 0.68) but not on unowned
games, so it is used for owned games only.

**The deployed model is exactly the evaluated pair**: the LightGBM model from the
training window plus the calibrator from the calibration window. Nothing is
refitted after evaluation.

## 4. Category ranking (spec §20, Prompt 5 C)

Satisfaction means predicted P(satisfied) × 100 when a model is deployed, otherwise Match.

| Category | Score | Settings |
|---|---|---|
| Owned | 0.85 · satisfaction + 0.15 · backlog | `owned_satisfaction_weight`, `owned_backlog_weight` |
| Unowned | 1.0 · satisfaction | `unowned_satisfaction_weight` |
| Trending | 0.80 · satisfaction + 0.20 · trend | `trending_satisfaction_weight`, `trending_trend_weight` |

- Weights are overridable through `RECOMMENDER_OVERRIDES`.
- **Satisfaction must carry at least half the weight** in every category; other
  values stop the app at startup.
- The global satisfaction model also sees the category as a feature.

## 5. Serving

`refresh_recommendations` loads the deployed model and computes features for every
candidate in a batch:
- items store `predicted_satisfaction`;
- runs store `satisfaction_model_version_id`, and `algorithm` becomes `content-v2[+cf#id][+sat#id]`;
- the API returns `score_kind = "calibrated_satisfaction"`.

Cards then show **"Predicted enjoyment 73%"**. The "Why this score" panel adds the
prediction and the ranking score, and Match stays visible.

**Fallbacks** (tested): ranking stays on Match, and recommendations keep working, when:
- no model is deployed;
- the artifact is missing, corrupt or fails its checksum;
- the feature schema differs;
- prediction raises.

## 6. Daily pipeline (Prompt 5 D)

`train_models` runs at 04:35 UTC on the `training` queue:

1. **Collaborative stage** (docs/COLLABORATIVE.md).
2. **Satisfaction stage**: prepare eligible data (opted-in, pseudonymised) → validate
   label counts → features → train → evaluate → compare with production → register
   → deploy only if all gates pass.

Each stage:
- writes a `training_runs` row (running, succeeded, skipped or failed);
- stores its evaluation report as JSON in the row, and as Markdown in
  `<models_dir>/reports/<kind>-<run>.md` on the `models` volume.

A crash in one stage is recorded and the next stage still runs. Deployed models are
untouched unless a new one passes its gates. After any deployment, recently active
players' lists are rebuilt.

**Determinism**: the same data trains the same model. Players are ordered by a
fingerprint of their signals, not by their per-run pseudonym, and LightGBM and ALS
run single-threaded with fixed seeds.

## 7. Versioning (Prompt 5 E)

`model_versions` stores, per model:
- version id and kind, and the training timestamp (`created_at`);
- dataset statistics, hyperparameters (including the calibration method) and the
  **feature schema version** (`sat-v1`, `cf-signals-v1`);
- evaluation metrics;
- artifact path and SHA-256, and deployment status.

Artifacts are JSON (LightGBM text format plus calibrator numbers; no pickles) on
the persistent `models` volume. `model_deployment_history` logs every deploy and
rollback. The 5 newest artifacts per kind are kept; retired ones are deleted after
30 days.

## 8. Administration (manual trigger, rollback)

There is deliberately **no admin HTTP endpoint** (spec §35). Administrators use the
CLI inside the worker container:

```bash
docker compose exec worker python -m app.cli train
```

That runs both stages now. `--only satisfaction` runs one stage; `--queue` sends it
to the worker. Other commands:

```bash
docker compose exec worker python -m app.cli models
docker compose exec worker python -m app.cli report
docker compose exec worker python -m app.cli rollback sat-20261201-043500-lgbm
docker compose exec worker python -m app.cli monitor
```

`report` prints the latest report per kind (or `report <run id>`).

## 9. Monitoring (Prompt 5 F)

`monitor_models` runs daily at 05:45 UTC (and on `app.cli monitor`). It stores one
`model_monitoring_reports` row per day: a 30-day window, metrics and alerts.

| Metric | How |
|---|---|
| Satisfaction rate | Ratings on recommended games, Liked or Loved share, by category, **with feedback coverage** (rated / recommended and played 2 h or more). Selection bias is noted |
| Negative feedback | Dislike, not my type and not interested per impression, by category |
| Calibration | Prediction stored on the recommendation vs the later rating: ECE and table |
| NDCG@5, precision@5 | Per run, explicit positives *still in place* after it was shown |
| Coverage, diversity | Distinct games in current top-10 lists / catalogue; 1 − mean pairwise tag cosine |
| Training failures | Failed runs in the window, by kind; deployed versions |
| Drift | PSI of predictions, Match and collaborative percentile (last 7 days) vs the model's training distributions |

**Alerts**:
- any failed training run;
- production ECE above 0.1 with at least 30 rows;
- any PSI above 0.2.

Metrics without data are reported as empty, never as zero.
