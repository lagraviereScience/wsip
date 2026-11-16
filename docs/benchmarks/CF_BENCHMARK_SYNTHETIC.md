# Collaborative filtering benchmark (synthetic players)

Date: 2026-11-15 · Command: `python -m app.cli benchmark-cf --seeds 3` · Code: `backend/app/machine_learning/`

> **These are synthetic players, not real users.** The deployment has one real
> player, and collaborative filtering needs many. The synthetic population tests
> that the models learn real structure and compares algorithms under controlled
> conditions. It says nothing about how well they will serve real players: that
> needs real interactions, and the daily pipeline measures it on real data before
> any model is deployed (see [COLLABORATIVE.md](../COLLABORATIVE.md)).

## Setup

- **Population** (`app/machine_learning/synthetic.py`): players have a *feature
  taste* (tags they like, learnable from metadata) and a *latent taste* (a hidden
  factor no tag reveals, learnable only from co-play). They own, play, rate, like,
  favourite, dislike and reject games through the same signal channels as real
  users, including owned-never-played games and price-based dismissals (which carry
  no signal).
- **Protocol** (`app/machine_learning/evaluation.py`): chronological split at the
  80th percentile of signal timestamps; test positives are later games reaching
  "saved / liked / favourite / positive rating / about 10 h of play"; users are
  folded in from their training interactions exactly as in production. The
  cold-item split removes all interactions of 15% of games from training.
- **Algorithms**: `popularity` and `content` (feature cosine) baselines;
  `implicit` ALS and BPR, each pure and hybrid (game features as pseudo-users).
  LightFM was not benchmarked: it does not build on Python 3.12 and the project
  owner chose to skip it for now (OPEN_QUESTIONS #24).

## Results

Synthetic population: 800 players, 500 games, 40 tags, 3 seeds (mean ± standard deviation). Never real data.

### warm split (759 test players on average)

| Algorithm | ndcg@5 | precision@5 | recall@20 | negative_rate@5 | coverage@5 | Fit (s) |
|---|---:|---:|---:|---:|---:|---:|
| popularity | 0.080 ± 0.021 | 0.056 ± 0.014 | 0.229 ± 0.027 | 0.020 ± 0.004 | 0.033 ± 0.001 | 0.00 |
| content | 0.061 ± 0.004 | 0.045 ± 0.004 | 0.237 ± 0.015 | 0.001 ± 0.000 | 0.582 ± 0.030 | 0.00 |
| als | 0.155 ± 0.006 | 0.104 ± 0.002 | 0.370 ± 0.002 | 0.004 ± 0.000 | 0.470 ± 0.013 | 0.15 |
| hybrid_als | 0.160 ± 0.003 | 0.105 ± 0.000 | 0.377 ± 0.005 | 0.005 ± 0.001 | 0.476 ± 0.016 | 0.13 |
| bpr | 0.137 ± 0.016 | 0.090 ± 0.010 | 0.323 ± 0.018 | 0.012 ± 0.000 | 0.236 ± 0.031 | 0.34 |
| hybrid_bpr | 0.133 ± 0.015 | 0.087 ± 0.007 | 0.320 ± 0.019 | 0.009 ± 0.001 | 0.273 ± 0.025 | 0.37 |

### cold_item split (708 test players on average)

| Algorithm | ndcg@5 | precision@5 | recall@20 | negative_rate@5 | coverage@5 | Fit (s) |
|---|---:|---:|---:|---:|---:|---:|
| popularity | 0.030 ± 0.011 | 0.018 ± 0.005 | 0.278 ± 0.037 | 0.020 ± 0.004 | 0.072 ± 0.001 | 0.00 |
| content | 0.287 ± 0.038 | 0.167 ± 0.026 | 0.705 ± 0.012 | 0.009 ± 0.002 | 0.957 ± 0.021 | 0.00 |
| als | 0.030 ± 0.011 | 0.018 ± 0.005 | 0.278 ± 0.037 | 0.020 ± 0.004 | 0.072 ± 0.001 | 0.13 |
| hybrid_als | 0.275 ± 0.030 | 0.155 ± 0.021 | 0.687 ± 0.010 | 0.008 ± 0.003 | 0.985 ± 0.012 | 0.14 |
| bpr | 0.030 ± 0.011 | 0.018 ± 0.005 | 0.278 ± 0.037 | 0.020 ± 0.004 | 0.072 ± 0.001 | 0.35 |
| hybrid_bpr | 0.106 ± 0.019 | 0.068 ± 0.006 | 0.490 ± 0.023 | 0.013 ± 0.005 | 0.773 ± 0.069 | 0.39 |

## Reading the results

- **Collaborative models learn what content cannot.** On games with interaction
  history, ALS roughly doubles popularity's NDCG@5 and beats the content baseline
  by 2.5×, because it also picks up the latent taste.
- **Hybrid ALS is the best all-rounder.** It matches ALS on known games (the
  difference is within the seed-to-seed spread) and, unlike pure ALS or BPR, ranks
  brand-new games almost as well as the content model. Pure collaborative models
  score exactly like popularity on new games: they know nothing about them.
- **BPR trails ALS** here and recommends more games users later rejected
  (negative rate 0.012 vs 0.004), partly because BPR cannot use explicit
  negatives in training. Its fold-in at serving time is an approximation.
- **Content stays essential** for new games and has the lowest negative rate, which
  is why production blends collaborative scores into the content Match instead of
  replacing it.
- All models train in under half a second at this size (single thread).

The daily pipeline picks the winner on real data each run; these synthetic
numbers do not pre-select it.
