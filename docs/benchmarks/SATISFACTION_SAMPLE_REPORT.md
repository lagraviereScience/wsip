# Sample satisfaction training report (synthetic players)

> **Synthetic data, not real players.** This is the unedited evaluation report of
> one daily-pipeline run on the *test* database, filled with 200 simulated players
> (`app/machine_learning/synthetic.py`, seed 21, every 10th player opted out). It
> shows what a real report contains and that the pipeline, gates and per-category
> check behave as designed. It does not predict quality on real players. Real
> reports are written to `<models_dir>/reports/` on every run.
>
> Reading it: overall the model beats the content baseline clearly (AUC 0.80 vs
> 0.68) and is calibrated (ECE ≤ 0.08). On unowned games alone content was better,
> so the deployed model is used for owned games only; unowned and trending keep Match.

## Report

- Started: 2026-11-15 04:35 UTC · trigger: manual · status: **succeeded**
- Decision: Deployed sat-20261115-043500-lgbm: AUC 0.8027, log loss 0.5267, ECE 0.0692 (content baseline AUC 0.6786). Used for: owned.

## Dataset

```json
{
 "labels": 2451,
 "features": 82,
 "last_label": "2026-07-02T23:39:28.147060+00:00",
 "first_label": "2026-01-01T12:40:16.162148+00:00",
 "label_policy": {
  "rating_weight": 1.0,
  "dislike_weight": 0.5,
  "favourite_weight": 0.5,
  "not_my_type_weight": 0.3,
  "positive_min_rating": 1
 },
 "positive_rate": 0.5333,
 "eligible_users": 180,
 "feature_schema": "sat-v1",
 "labels_by_source": {
  "dislike": 286,
  "favourite": 33,
  "not_my_type": 168,
  "rating:post_play": 1964
 },
 "never_labels_seen": {
  "like": 179,
  "click": 879,
  "playtime": 3252
 },
 "players_with_labels": 180,
 "collaborative_feature": "cross-fitted"
}
```

## Time-based splits

- test: 368 rows, 197 satisfied, 2026-06-07T22:20:52.829016+00:00 → 2026-07-02T23:39:28.147060+00:00
- train: 1715 rows, 932 satisfied, 2026-01-01T12:40:16.162148+00:00 → 2026-05-11T21:34:39.561207+00:00
- calibration: 368 rows, 178 satisfied, 2026-05-11T23:12:29.417108+00:00 → 2026-06-07T20:26:36.257977+00:00

## Test metrics (binary satisfaction)

| Model | auc | logloss | brier | ece | mean_predicted | observed_rate |
|---|---:|---:|---:|---:|---:|---:|
| lgbm_raw | 0.8002 | 0.5278 | 0.1754 | 0.0493 | 0.6289 | 0.5880 |
| base_rate | 0.5000 | 0.6781 | 0.2425 | 0.0161 | 0.6040 | 0.5880 |
| lgbm_calibrated | 0.8027 | 0.5267 | 0.1742 | 0.0692 | 0.5643 | 0.5880 |
| content_logistic | 0.6786 | 0.6360 | 0.2209 | 0.0480 | 0.6364 | 0.5880 |

## Calibration (isotonic, fitted on 368 rows)

| Bin | Rows | Predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 53 | 0.015 | 0.021 |
| 0.1-0.2 | 25 | 0.189 | 0.122 |
| 0.2-0.3 | 6 | 0.208 | 0.000 |
| 0.3-0.4 | 58 | 0.345 | 0.430 |
| 0.4-0.5 | 4 | 0.455 | 0.500 |
| 0.5-0.6 | 90 | 0.560 | 0.592 |
| 0.7-0.8 | 65 | 0.765 | 0.891 |
| 0.8-0.9 | 24 | 0.840 | 0.708 |
| 0.9-1.0 | 43 | 0.948 | 0.882 |

## Ranking within each player's test labels

| Model | ndcg@5 | players |
|---|---:|---:|
| lambdarank | 0.9606 | 98 |
| lgbm_calibrated | 0.9427 | 98 |
| content_logistic | 0.8984 | 98 |

## Ordinal satisfaction (investigated, not deployed)

```json
{
 "rows": 300,
 "lgbm_mae": 0.6777,
 "content_mae": 0.761,
 "lgbm_spearman": 0.516,
 "content_spearman": 0.3397
}
```

## By category

- owned (304 rows): LightGBM AUC 0.7598, content AUC 0.6741
- unowned (64 rows): LightGBM AUC 0.7418, content AUC 0.8596

## Top features (gain)

- owned_at_time: 1772.08
- cf_percentile: 721.93
- others_positive_rate: 561.86
- content_match: 538.36
- positive_points: 512.06
- pref_building: 273.15
- pref_zombies: 264.15
- group_genres_and_themes: 263.09
- pref_mining: 259.26
- pref_action: 238.82
- user_log_hours: 232.27
- pref_inventory-management: 221.55
- pref_psychological-horror: 200.46
- content_confidence: 200.0
- pref_auto-battler: 187.37

## Deployment gates

- ✅ enough test rows: 368 (need 40)
- ✅ both classes in test: 197 satisfied, 171 not (need 10 each)
- ✅ beats content baseline (AUC): 0.8027 vs 0.6786 + 0.01
- ✅ beats content baseline (log loss): 0.5267 vs 0.636
- ✅ calibrated: ECE 0.0692 (max 0.08)
- ✅ at least one category improves: owned: model, unowned: Match, trending: Match

