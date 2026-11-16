# PROMPT 5 — Satisfaction prediction and daily model training

Implement the specialised machine-learning training system.

This stage must transform the application's collected data into continuously improving recommendation models.

## A. Satisfaction model

Build a supervised satisfaction prediction model.

Its primary target must be explicit satisfaction.

Use post-play satisfaction ratings and appropriately weighted explicit feedback.

Keep separate:
- Satisfaction labels.
- Interest signals.
- Engagement signals.
- Exposure events.

Do not label a click as satisfaction.

Do not label a lack of interaction as dissatisfaction.

Do not label high playtime automatically as satisfaction.

Evaluate a LightGBM-based baseline.

Where appropriate, investigate:
- Binary satisfaction prediction.
- Ordinal satisfaction prediction.
- Ranking objectives.

Calibrate probability outputs before presenting them as predicted satisfaction.

## B. Model features

Potential inputs:
- Content compatibility.
- Collaborative filtering score.
- Player preference vector.
- Game feature vector.
- Player activity features.
- Historical satisfaction.
- Similar-player outcomes.
- Category information.
- Game popularity.
- Recommendation exposure context.

Avoid using features that would not be available at prediction time.

Prevent target leakage.

## C. Three category-specific ranking models

Implement:
- Owned game ranking.
- Unowned game ranking.
- Trending game ranking.

Use category-specific configurable weights.

The global satisfaction prediction should remain the main signal.

## D. Daily training pipeline

Implement scheduled daily training.

The pipeline must:
1. Prepare eligible datasets.
2. Validate them.
3. Generate features.
4. Train collaborative models.
5. Train satisfaction models.
6. Evaluate models.
7. Compare against production.
8. Register artifacts.
9. Deploy only if quality criteria pass.
10. Retain rollback capability.

## E. Model versioning

Store:
- Version identifier.
- Training timestamp.
- Dataset information.
- Hyperparameters.
- Feature schema version.
- Evaluation metrics.
- Artifact location.
- Deployment status.

Model artifacts must be stored persistently.

## F. Model monitoring

Track:
- Satisfaction rate.
- Negative feedback.
- Satisfaction prediction calibration.
- NDCG@5.
- Precision@5.
- Coverage.
- Diversity.
- Training failures.
- Model drift.

Use time-based evaluation splits.

Do not deploy a new model merely because it has completed training.

If insufficient training data exists, retain the previous model.

## Acceptance criteria

- Daily training can be scheduled.
- Training can also be triggered manually by administrators.
- Models are versioned.
- Models are evaluated before deployment.
- Rollback works.
- Users continue receiving recommendations if training fails.
- The satisfaction model is not trained on unqualified click events.
- The system works without a GPU.
- Evaluation reports are generated and stored.
