# ADR-0019: Point-in-time LightGBM satisfaction model, calibrated before display

- Status: Accepted · Date: 2026-11-15 · Stage 5

## Context
Prompt 5 asks for a supervised satisfaction model whose target is explicit
satisfaction. Interest, engagement and exposure must stay separate from labels.
Leakage must be prevented, and features must be available at prediction time.
Probabilities must be calibrated before being shown. There must be category-specific
rankers with satisfaction as the main signal, plus daily training with versioning,
rollback, monitoring and stored reports, all without a GPU. Spec §18 names LightGBM;
§35 forbids exposed admin endpoints.

## Decision
1. **Labels**: ratings at full weight, plus favourite (0.5), dislike (0.5) and not my
   type (0.3) for unrated games. Clicks, likes, saves, "not interested",
   playtime and no interaction are never labels.
2. **Point-in-time features**: each training row comes from the player's state just
   before the label, with the labelled game removed. Serving runs the same code at
   "now". The collaborative feature is **cross-fitted**: item factors from other
   players and earlier data, the player folded in without the labelled game.
3. **Time-based split** of 70% train, 15% calibration and 15% test. **LightGBM binary**
   is the deployable model, beaten-or-not against a content-only logistic baseline.
   **Isotonic or Platt calibration** is fitted on the calibration window. LambdaRank
   and ordinal regression are evaluated and reported but not deployed.
4. **Deploy the evaluated pair**, never a refit, and only if all gates pass: data
   volume, AUC lift and log loss versus content, ECE ≤ 0.08, and no clear regression
   versus production. The UI shows "Predicted enjoyment %" only for a deployed,
   calibrated model; otherwise "Match".
5. **Category rankers are linear on top of the global prediction**, with configurable
   weights (spec §20 defaults). Satisfaction must carry at least half the weight,
   validated at startup.
6. **One daily task** runs both stages in isolation. Every run stores a JSON and
   Markdown report. Administration happens through the CLI in the worker container,
   with no HTTP admin surface.
7. **Monitoring** is a daily stored report: satisfaction rate with coverage, negative
   feedback, production calibration, online NDCG and precision, coverage, diversity,
   training failures and PSI drift, with alerts.

## Alternatives considered
- **Category-specific LightGBM models**: rejected for now. There are too few labels
  per category, and the prompt asks the global prediction to stay the main signal.
  The category is a feature instead.
- **Refitting on all data after evaluation**: rejected. The deployed model would be
  unevaluated, and the calibrator would no longer match it.
- **An admin web page or API**: rejected (spec §35). The CLI needs container access,
  which is already the operator's trust boundary.
- **Training on current profiles**: rejected. Current profiles include the labels
  themselves (ratings feed the satisfaction component): target leakage.

## Consequences
- Building the dataset recomputes a profile per label, which is fine for thousands of
  labels. Caching per player and time bucket is the scaling path.
- Snapshots exist only since Stage 2 imports. Older playtime is estimated from the
  first snapshot.
- Item factors in the cross-fit include other players' data from inside the training
  window, which is minor, documented leakage. Test-window rows are clean.
