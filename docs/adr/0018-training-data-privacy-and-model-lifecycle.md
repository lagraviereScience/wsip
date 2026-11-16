# ADR-0018: Pseudonymous training, factor-only artifacts, gated deployment

- Status: Accepted · Date: 2026-11-15 · Stage 4

## Context
Prompt 4 F requires a global training opt-out, user data isolation, pseudonymised
training datasets and deletion handling. Spec §24 requires daily training that
deploys only when quality requirements are met and keeps earlier versions for
rollback. Spec §34 forbids claiming perfect machine unlearning.

## Decision
1. **Training reads only active accounts with `contribute_to_global_training`.** A
   missing settings row counts as opted out.
2. **One-off pseudonyms.** Each dataset build uses `HMAC-SHA256(random salt, user id)`
   and discards the salt afterwards. Datasets live only in memory during the run.
3. **Artifacts hold item factors only**: an `.npz` file with no pickles, verified by
   SHA-256 on load. Users are folded in at serving time from their own current
   data. So artifacts contain no per-user rows, opted-out and new users are still
   served, and deleting an account never requires editing a model file.
4. **Gated deployment.** The best collaborative model must beat popularity by 5% on
   NDCG@5, not raise the explicit-negative rate, and not fall below 90% of the
   deployed model. The pipeline also requires minimum data (25 players, 500
   positive pairs, 10 test players). Otherwise the run is "skipped" or "kept", and
   recommendations stay content-based.
5. **Lifecycle.** The previous model is retired, not deleted. The 5 newest artifacts
   are kept for rollback, and retired ones are deleted after 30 days. An account
   deletion makes the next scheduled run retrain even without new data. Deletions
   are recorded as timestamps only.

## Consequences
- A deleted account's influence on item factors lasts until the models trained with
  it are replaced and pruned. This is documented, not hidden (docs/PRIVACY.md).
- The deployed model is compared using its *recorded* metric, because re-evaluating
  it on today's window would leak training data. Comparisons across windows are
  therefore approximate.
- Synthetic players exist only for tests and benchmarks and never reach a
  deployable training run, which reads the database only.
