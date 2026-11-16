# Machine-learning methodology

How the app learns what people enjoy, end to end. Details live in the linked
documents; this page is the map.

## Layers

```
signals ──► individual profile ──► content Match ─┐
   │                                              ├─► P(satisfied) ─► category ranking
   └──► pseudonymised dataset ─► collaborative ───┘     (LightGBM,      (owned / unowned
                                 model (ALS/BPR)          calibrated)     / trending)
```

| Layer | What | Learns from | Document |
|---|---|---|---|
| Individual profile | Preference strength and confidence per canonical feature | Ratings (satisfaction), feedback reactions, lifetime and recent playtime (behaviour), manual settings (override) | [RECOMMENDATIONS.md](RECOMMENDATIONS.md) §2, [BEHAVIOUR.md](BEHAVIOUR.md) §3 |
| Content Match | Explainable compatibility of a game with the profile | No training: formulas over the profile and game metadata | [RECOMMENDATIONS.md](RECOMMENDATIONS.md) §3 |
| Collaborative model | Item factors from many players' interactions (implicit ALS/BPR, hybrid with game features) | Typed, weighted signals of players who allow training | [COLLABORATIVE.md](COLLABORATIVE.md) |
| Satisfaction model | Calibrated probability a player will enjoy a game | Explicit satisfaction labels only; point-in-time features | [SATISFACTION.md](SATISFACTION.md) |
| Category ranking | Owned, unowned and trending lists | Configurable weights; satisfaction always the main signal | [SATISFACTION.md](SATISFACTION.md) §4 |

## Principles

- **Playtime is not satisfaction**, clicks are not satisfaction, and no interaction is
  unknown, not negative. Signals are typed by channel
  ([COLLABORATIVE.md](COLLABORATIVE.md) §1); labels are explicit judgements only
  ([SATISFACTION.md](SATISFACTION.md) §1).
- **No leakage**: training rows see only what was known before the label, with the
  labelled game removed; the collaborative feature is cross-fitted; evaluation splits
  are by time.
- **Gated deployment**: a model replaces production only if it beats the baselines
  (popularity; content-only) on held-out later data and is calibrated. Otherwise the
  previous model, or the content baseline, keeps serving.
- **Nothing collective is invented**: below 25 players / 200 labels nothing is
  deployed, and no "players like you" claim is shown.
- **Personal beats global**: manual preferences override everything; explicit
  negatives are hard filters; a per-category check keeps Match where the model ranks
  worse.
- **Privacy**: opted-out players are never in training data; datasets are
  pseudonymised with a one-off salt and never stored; artifacts hold no per-player
  rows ([PRIVACY.md](PRIVACY.md)).
- **CPU only, reproducible**: single-threaded, seeded; the same data trains the same
  model. Daily training at the current synthetic scale takes about 20 s
  ([PERFORMANCE.md](PERFORMANCE.md)).

## Lifecycle

Daily `train_models` (04:35 UTC): collaborative stage, then satisfaction stage. Each
stage prepares, validates, trains, evaluates, compares with production, registers
and deploys only if every gate passes; retains five versions for rollback; writes an
evaluation report. Daily `monitor_models` (05:45) tracks satisfaction rate (with
feedback coverage), negative feedback, production calibration, online NDCG@5 and
precision@5, coverage, diversity, training failures and drift.
Administration: `python -m app.cli train | models | report | rollback | monitor | status`.

## Evaluation reports

- Every training run: `training_runs.report` (JSON) and `<models>/reports/<kind>-<run>.md`.
- Synthetic benchmarks: [benchmarks/CF_BENCHMARK_SYNTHETIC.md](benchmarks/CF_BENCHMARK_SYNTHETIC.md),
  [benchmarks/SATISFACTION_SAMPLE_REPORT.md](benchmarks/SATISFACTION_SAMPLE_REPORT.md).
- Real players: none yet. The deployment has one player; both models correctly
  decline to train (see the Stage 6 report).

## Current limits

- LightFM not used (does not build on Python 3.12; owner's decision, OPEN_QUESTIONS #24).
- Satisfaction and collaborative gates are starting values to revisit with real data
  (OPEN_QUESTIONS #28, #29).
- Calibration is checked offline and monitored in production; "Predicted enjoyment"
  appears only for a deployed model that passed it.
