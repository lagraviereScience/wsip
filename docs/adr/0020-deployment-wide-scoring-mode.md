# ADR-0020: Deployment-wide scoring mode (AI_GRADE) selected in one engine module

- Status: Accepted · Date: 2026-11-15 · After Stage 6 (owner request)

## Context
The owner wants one environment variable, `AI_GRADE`, to switch the whole deployment
between two modes:

- the machine-learning engine: collaborative filtering and the calibrated
  satisfaction model, with their documented fallbacks;
- a genuinely non-machine-learning, deterministic scoring mode, with no model
  inference and no scheduled training.

The setting is global, not per user. Requirements:

- An invalid value must be a clear error, never a silent choice.
- The selection must be central; no page or endpoint may bypass it.
- Cached lists must carry their mode, and a score must never be shown under the
  other mode.
- Switching must need no migration and must delete nothing.

Before this decision, model loading already happened in one place
(`load_context`), and the content-based engine (ADR-0016) is deterministic.

## Decision
1. **Setting:** `ai_grade: bool = True` in `Settings`. A `before` validator accepts
   only `true` or `false`, in any case, and rejects pydantic's usual extras
   (`1/0/yes/no/on/off`, empty). Settings also hide raw input in validation errors,
   so a configuration error never echoes secrets.
2. **One selection point:** `app/recommendations/engines.py` defines
   `MachineLearningRecommendationEngine` and `ClassicRecommendationEngine`.
   - An engine supplies only the trained scorers (`TrainedScorers`) to the shared
     ranking code.
   - `load_context` and `generate_all` take the active engine from settings unless
     one is passed.
   - Candidate generation, eligibility, exclusions, category formulas and the
     result structure are shared.
   - The classic engine never imports ML packages or reads artifacts. The ML engine
     contains loader failures and falls back per model.
3. **Runs carry their mode:** migration 0008 adds `recommendation_runs.scoring_mode`
   (`ai`/`classic`, existing rows `ai`) and `config_version` (a fingerprint of mode
   + parameters).
   - The API serves only the latest list, and only if its mode matches the active
     one. Otherwise it answers `pending` and queues a rebuild.
   - A changed `config_version` in the same mode is served, and a rebuild is queued.
   - The frontend additionally ignores predictions on classic runs.
4. **Training:** the scheduled `train_models` and `monitor_models` tasks return
   `skipped` in classic mode. An administrator's explicit `app.cli train` still runs,
   with a notice. Event collection, models and the registry are untouched.
5. **Observability:**
   - `/api/health/ready` returns `scoring_mode`;
   - start-up logs of the API, worker and scheduler state `AI` or `CLASSIC`;
   - each rebuild logs its mode and algorithms;
   - `app.cli status` and `app.cli check-config` show the mode.

## Consequences
- One switch, read at start: changing it means recreating the backend services
  (`docker compose up -d`). There is no hot reload, by design.
- After a switch, each user's first visit shows the waiting state for a few seconds
  while lists rebuild. No stale score from the other mode is ever shown.
- Lists from the inactive mode remain in the database until normal retention removes
  them. Nothing is deleted on a switch.
- Adding a new recommendation surface requires reading lists through the same
  endpoint or `generate_all`. This is noted in [SCORING_MODES.md](../SCORING_MODES.md).
- Tests:
  - `tests/unit/test_scoring_mode.py`;
  - `tests/integration/test_scoring_modes.py`;
  - frontend classic-mode tests;
  - a production-mode deployment test switching TRUE → FALSE → invalid → TRUE.
