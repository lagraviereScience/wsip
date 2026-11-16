# Scoring modes: AI_GRADE

One environment variable chooses how recommendations are scored, for every user of a
deployment:

```
AI_GRADE=TRUE    # default: machine-learning mode ("AI")
AI_GRADE=FALSE   # classic, deterministic scoring ("CLASSIC")
```

Only `TRUE` or `FALSE` is accepted, in any case. Any other value (`1`, `yes`, an empty
string) is a configuration error: the services refuse to start, `migrate` logs
`AI_GRADE must be TRUE or FALSE (case-insensitive), got '...'`, and
the optional `scripts/check-env.sh` explains it in plain words. It is a deployment setting, not
a user preference. Changing it takes `docker compose up -d`, which recreates migrate,
backend, worker and scheduler ([tutorial.md](../tutorial.md), section G).

## Engine selection

All selection happens in one module, `backend/app/recommendations/engines.py`:

```
RecommendationService  (app/services/recommendations.py: load_context, generate_all)
    |
    |-- AI_GRADE=TRUE  -> MachineLearningRecommendationEngine
    |                     loads the deployed collaborative model and the calibrated
    |                     satisfaction model, each only if it is deployed, valid and
    |                     applicable to this player; otherwise None (fallback)
    |
    |-- AI_GRADE=FALSE -> ClassicRecommendationEngine
                          never imports the ML packages, never reads an artifact
```

An engine supplies only the trained scorers (`TrainedScorers`) to the shared ranking
code. Everything else is identical in both modes, from the same code path:

- the catalogue and canonical taxonomy;
- player data, ownership, manual preferences and explicit exclusions (hard filters);
- candidate eligibility rules;
- the category formulas;
- the result structure the API and frontend read.

Nothing else in the application checks the mode, except two places:

- the training and monitoring tasks, which skip themselves;
- the API, which serves a list only in the mode that built it.

| | AI mode | Classic mode |
|---|---|---|
| Content compatibility (Match): genres and themes, mechanics, modes, structure, pace and complexity; lifetime and recent playtime, last played; manual preferences; exclusions | ✓ | ✓ |
| Owned: Match + backlog | ✓ (Match or predicted satisfaction) | ✓ (Match) |
| Unowned: Match | ✓ (+ collaborative blend and candidates, predicted satisfaction) | ✓ |
| Trending: Match + validated trend score | ✓ (+ models) | ✓ |
| Collaborative filtering inference | when a model is deployed and the player has ≥ 3 positives | never |
| Satisfaction model inference | when deployed and enabled for the category | never |
| Scheduled daily training and model monitoring | run | skipped (logged) |
| Behaviour events, feedback, ratings, playtime history | collected | collected (same privacy rules) |
| Model artifacts and registry | used | kept intact, untouched |

Classic scoring is deterministic: the same data and configuration give the same
scores and order (tested). Its formulas and weights are the documented content-based
engine ([RECOMMENDATIONS.md](RECOMMENDATIONS.md)), configurable through
`RECOMMENDER_OVERRIDES`. No randomness, no LLM, and explanations come from the score
contributions.

### Fallbacks in AI mode

AI mode never fails because of a model. If no model is deployed, the data is
insufficient, or an artifact is missing or corrupt, that scorer is `None` and the
list is ranked on Match, as documented in [COLLABORATIVE.md](COLLABORATIVE.md) and
[SATISFACTION.md](SATISFACTION.md). The run's `algorithm` then shows only `content-v2`.
Loader exceptions are logged and contained in the engine.

## Stored lists and switching modes

Every recommendation run stores:

- `scoring_mode`: `ai` or `classic`;
- `config_version`: a 12-character fingerprint of the mode and every scoring parameter;
- `algorithm`, e.g. `content-v2+cf#3+sat#5`, with the model version ids.

The API (`GET /api/me/recommendations/{category}`, used by the dashboard, "Games I
Should Play", "Games I Should Buy" and "Trending Games") serves only the **latest**
list per category, and only if it was built in the **active** mode:

- **Other mode** (just switched, either way): the list is not shown, the response is
  `status: "pending"` and a rebuild is queued. The page shows its waiting state and
  reloads once the new list exists. An AI prediction can therefore never be shown in
  classic mode, nor a classic score presented as a prediction. The frontend also
  ignores `predicted_satisfaction` when `run.scoring_mode` is `classic`.
- **Same mode, different `config_version`** (parameters changed): the list is served
  and a rebuild is queued.

Switching needs no migration and deletes nothing. Lists from the other mode simply
stop being served and age out under the normal retention rules
([DATABASE.md](../DATABASE.md)). Switching back to `TRUE` resumes scheduled training,
and the previously deployed models are validated as they load and used again.

The dashboard's **Refresh** button and every automatic rebuild (after feedback,
sync or training) go through `generate_all`, which uses the active engine. The
"Popular right now" panel always uses the classic engine: it is an absolute player
count personalised by Match, in both modes.

The product has no "Suggest another one" feature. If one is added, it must take its
list from the same endpoint, or call `generate_all`, to respect the mode.

## Observability

| Where | What |
|---|---|
| `GET /api/health/ready` | `"scoring_mode": "ai"` or `"classic"`, and nothing about models |
| Start-up logs | backend `startup`, worker and scheduler `scoring mode`, each with `scoring_mode: AI` or `CLASSIC` |
| Worker logs | each rebuild logs `scoring_mode` and the `algorithms` used; skipped training logs `daily training skipped` |
| `python -m app.cli status` | `scoring_mode` and the number of lists built per mode in 24 h |
| `python -m app.cli check-config` (also run with `--quiet` by `migrate` on every start) | `AI_GRADE` and the resulting mode |
| API responses | `scoring_mode` on the list, and `run.scoring_mode`, `run.config_version` and `run.algorithm` per list |
| Website | list header says "with classic scoring … no machine learning" in classic mode |

## Tests

- `backend/tests/unit/test_scoring_mode.py`:
  - default, case-insensitive and invalid values;
  - the configuration check;
  - engine selection;
  - classic never loads a model;
  - AI with models, and AI with missing or broken models;
  - configuration fingerprint;
  - scheduled training and monitoring in both modes.
- `backend/tests/integration/test_scoring_modes.py`:
  - both engines on a population with deployed models;
  - classic is deterministic and loads no model;
  - AI uses the models and falls back when the artifacts vanish;
  - all three lists in classic mode, including trend scores;
  - switching modes through the API in both directions, with the Refresh button;
  - a parameter change;
  - events still collected in classic mode.
- `frontend/src/components/recommendations/recommendations.test.tsx`: classic wording;
  a prediction is never shown in classic mode.
- Deployment test (2026-11-15): switching a running production-mode stack to `FALSE`
  and back, and an invalid value stopping the start.
