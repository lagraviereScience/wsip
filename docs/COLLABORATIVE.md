# Collaborative filtering (Stage 4)

Collective learning from players' behaviour (spec §17, §19, §23–§25, Prompt 4 D–F).
Decisions: [ADR-0009](adr/0009-collaborative-filtering-library.md) (amended) and
[ADR-0018](adr/0018-training-data-privacy-and-model-lifecycle.md). Benchmark:
[benchmarks/CF_BENCHMARK_SYNTHETIC.md](benchmarks/CF_BENCHMARK_SYNTHETIC.md).

| Part | Code (`backend/app/`) |
|---|---|
| Signals, pseudonymised dataset | `machine_learning/datasets/interactions.py` |
| Models (ALS, BPR, hybrids, baselines) | `machine_learning/models/factorization.py` |
| Splits and metrics | `machine_learning/evaluation.py` |
| Benchmark and synthetic players | `machine_learning/benchmark.py`, `machine_learning/synthetic.py` |
| Daily pipeline, deployment, rollback | `machine_learning/training/pipeline.py` |
| Artifacts | `machine_learning/registry/store.py` |
| Serving | `recommendations/candidate_generation/collaborative.py` |

## Current state

**No collaborative model is deployed, and none will be until there are enough real
players.** Training is skipped below **25 players** who allow training and **500
positive interactions** (`CF_MIN_USERS`, `CF_MIN_POSITIVE_PAIRS`). On 2026-11-15 the
data was 1 player and 265 positive interactions.

Until a model passes its gates:
- every recommendation is content-based (`algorithm = content-v2`);
- no card claims "players like you…".

Nothing collective is invented.

## 1. Signals: not every event is a positive

| Channel | Source | Value (rating points) |
|---|---|---|
| Satisfaction | Ratings: Loved +6, Liked +4, Neutral −1, Disliked −4, Hated −6 | Decides alone; the latest rating wins |
| Interest | Favourite +4, like +2.5, save for later +1.5 | Positive |
| Negative | Dislike −4, not my type −4, "not interested" for no or another reason −1 | Overrides positives |
| Engagement | Steam playtime, `3 · ln(1+h)/ln(101)` (100 h = 3) | Positive, supporting |
| Weak | Click 0.3, game page 0.3, Steam Store visit 0.5, capped at 1.0 total | Positive, weak |
| Ownership | Owned, never played | **Not a signal** (counted in stats only) |
| Exposure | Shown but never interacted with | **Unknown** (counted in stats only) |
| Price or timing | "Not interested" because of price, timing or owning it elsewhere | **No signal** |

Per player and game:
- a rating decides on its own;
- otherwise any explicit negative wins;
- otherwise interest + engagement + weak signals add up, capped at 8.

Clicks alone can never make a game count as "relevant" in evaluation; relevance
starts at 1.5.

## 2. Models

All share one interface: `fit`, `fold_in`, `scores`. Confidence follows Hu, Koren &
Volinsky:
- positive values become preference 1 with confidence `1 + α·v`;
- negative values become preference 0 with confidence `1 + α·|v|`.

| Algorithm | Notes |
|---|---|
| `als` | `implicit` ALS: 32 factors, λ = 0.05, 20 iterations, single thread, fixed seed |
| `hybrid_als` | ALS plus one **pseudo-user per game feature**, interacting with every game that has the feature (weight 2 × rolled share × metadata confidence). Item factors reflect co-play *and* metadata |
| `bpr` / `hybrid_bpr` | `implicit` BPR on positives only (BPR has no explicit negatives), same hybrid option |
| `popularity`, `content` | Baselines, never deployed |

**LightFM** (spec §17, Prompt 4) is not used. Its last release (2023) and its pinned
source fail to build on Python 3.12; regenerating its C code needs patching an
unmaintained native extension. On 2026-11-15 the project owner chose to skip it for
now (OPEN_QUESTIONS #24). The hybrid ALS covers what LightFM's item features would
have given: metadata-aware item factors for cold-start games.

## 3. Daily pipeline (spec §24)

Since Stage 5 the collaborative stage is the first step of the daily `train_models`
task (04:35 UTC, `training` queue), followed by the satisfaction stage
([SATISFACTION.md](SATISFACTION.md)). Run it alone with `python -m app.cli train --only
collaborative`. Players are ordered by a fingerprint of their own signals, not by
their per-run pseudonym, so the same data always trains the same model.

1. **Collect**: active users who allow training. A missing settings row counts as
   opted out.
2. **Pseudonymise**: `HMAC-SHA256(salt, user id)`, with a random salt per build that
   is never stored.
3. **Validate**: enough players and positive pairs. A scheduled run also needs at
   least 2% more positive pairs than the deployed model, or an account deletion
   since it was trained. Otherwise the run is `skipped`.
4. **Features**: rolled-up feature shares × confidence for every catalogue game.
5. **Train and evaluate** all six algorithms on:
   - a **chronological** warm split (80/20 by signal time);
   - a **cold-item** split (15% of games held out entirely).

   Users are folded in from their training interactions exactly as served.
   Every metric is stored in `evaluation_results`.
6. **Gates**:
   - at least 10 test players;
   - the best collaborative model's NDCG@5 ≥ **1.05 ×** popularity's;
   - its negative rate@5 ≤ popularity's + 0.02;
   - not below **90%** of the deployed model's recorded NDCG@5.
7. **Deploy**:
   - retrain the winner on all data and write the artifact;
   - mark it `deployed`; the previous version becomes `retired`;
   - log the change in `model_deployment_history`;
   - rebuild lists for players active in the last 14 days.

**Keep and roll back**:
- The newest 5 artifacts are kept, and none retired for more than 30 days.
- `python -m app.cli rollback-cf <version>` redeploys a kept version.

Caveat: the comparison with the deployed model uses its recorded metric from an
earlier test window, not a re-evaluation on today's window. That would leak
training data, because the deployed model was trained on it.

## 4. Serving

`load_collaborative` runs when lists are rebuilt.

**Fold-in.** The user's vector is computed from their **own current signals** and the
model's item factors:
- `x = (YᵀY + Σ(|c|−1)yyᵀ + λI)⁻¹ Σ_{c>0} c·y`
- This matches `implicit`'s own solver; a unit test checks it.

Consequences:
- Artifacts never contain user rows.
- Feedback given minutes ago counts.
- Users who joined after training, or opted out of it, are still served from their
  own data, without contributing to the model.

**Cold start** (Prompt 4 E):
- A user needs **at least 3 positive interactions** with modelled games. Below that,
  content-based only.
- A game the model has never seen gets no collaborative score: metadata decides.
  With hybrid ALS deployed, games that have features but no interactions still get
  metadata-based factors.

**Candidates.** The unowned category adds the model's top 100 games for the user
to the content candidates (spec §19 candidate union). Owned, rated and explicitly
rejected games are never candidates.

**Blending.** The collaborative score becomes a **percentile** (0–100) among
modelled games:
- `Match = (1 − w) · content Match + w · percentile`
- `w = 0.3 · min(1, positives / 10)`, so thin evidence counts less (`CF_BLEND_WEIGHT`)

Where the blend shows:
- The card's "Why this score" panel shows the percentile.
- The run's `algorithm` becomes `content-v2+<version>`, with `model_version_id` set.
- Events record that version.
- A "players with libraries like yours" reason appears only when the percentile is
  at least 90 and the weight is at least 0.1.

**Match remains an uncalibrated score.** The calibrated satisfaction model (LightGBM,
spec §18) needs post-play ratings and is not part of this stage.

## 5. Evaluation (spec §25)

Metrics are NDCG@5, precision@5, recall@20, negative rate@5 and coverage@5, over
both splits, for every algorithm on every run.

Known gaps, documented rather than hidden:
- Satisfaction rate and feedback coverage need post-play ratings at volume.
- Selection bias: only some users answer, which will matter when evaluating on
  ratings.
- A/B testing needs traffic.
