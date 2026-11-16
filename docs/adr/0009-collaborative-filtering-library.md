# ADR-0009: `implicit` instead of LightFM for collaborative filtering

- Status: Accepted, implemented in Stage 4 (amended 2026-11-15) · Date: 2026-11-14

## Context
Spec §17 asks to evaluate LightFM and `implicit`. LightFM is effectively unmaintained and has known build problems on Python ≥ 3.12 (ADR-0005).

## Decision
Use `implicit` (ALS, optionally BPR) for collaborative filtering. Hybrid behaviour comes from combining it with the content-based baseline and feeding both into the LightGBM satisfaction model. Users who opt out of global training are served by folding in their interactions at inference time against fixed item factors, without contributing to training. LightFM remains an optional offline evaluation candidate only.

## Consequences
- No dependency on an unmaintained native extension.
- Item cold-start is handled by the content model, not by LightFM-style item features inside the CF model.
- Set BLAS threads explicitly for training jobs (the backend image defaults them to 1).

## Amendment (Stage 4, 2026-11-15)
- Prompt 4 asked to implement **and benchmark** LightFM. It was checked again: the
  1.17 release and the pinned source (commit `0c9c31e`) fail to build on Python
  3.12, and the source's pre-generated C does not compile against 3.12's headers.
  Options offered: a community fork with wheels, patching the official source, or
  skipping it. **The project owner chose to skip LightFM for now** (OPEN_QUESTIONS #24).
- `implicit` 0.7 is used for **ALS and BPR**, each also in a **hybrid** variant: game
  features are added as pseudo-users, so item factors also reflect metadata. This
  gives LightFM-style cold start for new games inside the collaborative model, in
  addition to the content model. Synthetic benchmark:
  [CF_BENCHMARK_SYNTHETIC.md](../benchmarks/CF_BENCHMARK_SYNTHETIC.md).
- The runtime image installs `libgomp1` (OpenMP runtime for `implicit`). Training
  runs single-threaded.
