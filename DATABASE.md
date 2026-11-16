# Database

PostgreSQL 18 is the single source of truth. Redis holds only ephemeral data
(cache, later job queues). Losing Redis must never lose user data.

## Roles

Created on first start with an empty volume by [`docker/postgres/initdb/01-roles.sh`](docker/postgres/initdb/01-roles.sh),
which runs the idempotent [`docker/postgres/provision.sh`](docker/postgres/provision.sh).
Both are packaged in the `wdywtp-postgres:1.0` image
([docker/postgres/Dockerfile](docker/postgres/Dockerfile), built by `build.sh`) and run
by the official PostgreSQL entrypoint only when the data volume is empty. With
existing data, PostgreSQL logs "Skipping initialization" and nothing is re-run
([ADR-0004](docs/adr/0004-least-privilege-database.md)). The same script creates the isolated
`<DB_NAME>_test` database for integration tests (`test-db-init` service).

| Role | Env vars | Privileges | Used by |
|---|---|---|---|
| superuser | `POSTGRES_SUPERUSER(_PASSWORD)` | everything | the postgres container, backups, emergencies |
| schema owner | `DB_MIGRATION_USER/PASSWORD` | owns database `DB_NAME` and every table | `migrate` service (Alembic) only |
| runtime | `DB_USER/PASSWORD` | `CONNECT`, `TEMP`, `USAGE` on `public`; `SELECT/INSERT/UPDATE/DELETE` on tables and `USAGE/SELECT` on sequences via default privileges | backend API (later: workers) |

The runtime role **cannot create, alter or drop** objects. An integration test
checks this. Default privileges apply automatically to every table that
migrations create.

> Init scripts run only when the data volume is empty. To change role passwords
> on an existing database, use `ALTER ROLE ... PASSWORD` as the superuser and
> then update `.env`.

## Migrations

- Alembic, configured in `backend/alembic.ini` and `backend/app/database/migrations/`.
- The URL is never stored in a file. `env.py` builds it from environment variables
  and connects as the schema owner.
- File names: `YYYYMMDD_<rev>_<slug>.py`. Constraint and index names follow
  the fixed naming convention in `app/database/base.py`, so autogenerate is stable.
- Each migration runs in its own transaction (`transaction_per_migration`).
- The `migrate` Compose service runs `alembic upgrade head` before the backend
  starts. `/api/health/ready` fails if the database revision differs from the
  code's head.

Create a migration (after adding models to `app/models/` and importing them in
`app/models/__init__.py`):

```bash
cd backend && uv run alembic revision -m "describe change"   # or --autogenerate against a dev database
```

Deployments apply new migrations automatically: `./build.sh && docker compose up -d`
runs the `migrate` service (`alembic upgrade head`, pending revisions only).

Every migration must have a working `downgrade()`. The integration suite runs
`downgrade base` followed by `upgrade head`.

### Current revisions

| Revision | Content |
|---|---|
| `0001` baseline | Sets the database default `timezone` to `UTC`. Establishes the chain. |
| `0002` | Users, sessions, catalogue, taxonomy, activity (18 tables, see below). |
| `0003` | Sign-in-only mode: `user_library.source` (steam_import/manual), nullable playtime with no default, `user_feedback` ratings (ADR-0014). |
| `0004` | Stage 3: manual preferences and their history, profile runs, inferred preference vectors (+ history), recommendation runs and items, game prices, discovery provenance, player-count samples and daily aggregates (11 tables, see below). |
| `0005` | Stage 4: `behaviour_events` (append-only, enforced by a trigger), `user_game_reactions`, `satisfaction_prompts`, the model registry (`training_runs`, `model_versions`, `evaluation_results`, `model_deployment_history`) and `account_deletions`. Adds a feedback component to inferred preferences, `model_version_id` to runs and `collaborative_score` to items, and widens `recommendation_runs.algorithm` to 64 characters. `user_feedback.source` also accepts `already_played`. |
| `0006` | Stage 5: `model_monitoring_reports`; `training_runs.report` (JSONB) and `report_path`; `model_versions.feature_schema_version`; `recommendation_runs.satisfaction_model_version_id`; `recommendation_items.predicted_satisfaction`. |
| `0007` | Stage 6: `player_count_passes` (one row per player-count sampling pass: source freshness and reliability), `game_completion_times` (IGDB time to beat with source and fetch time), `recommendation_runs.duration_ms` (generation latency). |

After migrating, the `migrate` service runs `python -m app.cli sync-taxonomy`. It idempotently
upserts the canonical taxonomy from `app/taxonomy/seed.py` and re-derives feature values whose
mapping version is out of date ([ADR-0012](docs/adr/0012-taxonomy-as-code.md)).

## Conventions (apply to all future tables)

- **Timestamps** are `timestamptz` and stored in UTC (sessions are also forced to
  UTC by the engine and by the database default).
- **Playtime** is stored as integer **minutes** (spec §12, §26).
- **Primary keys**: canonical internal IDs. External IDs (Steam AppID, IGDB,
  RAWG, ...) go in separate tables, never on the canonical record (spec §8).
- **Unknown ≠ absent**: unknown values are `NULL`, never `0` or `false` (spec §10, §14).
- **JSON (`jsonb`)** only for genuinely variable metadata, never instead of
  relational modelling.
- **Append-only history**: behaviour events and playtime snapshots are never
  rewritten when a profile changes. They are deleted only through account
  deletion workflows.
- Foreign keys, unique constraints and indexes are declared explicitly in models.

## Schema (Stages 2–3)

### Users

| Table | Purpose | Key constraints |
|---|---|---|
| `users` | Account; `id` is a time-ordered UUIDv7 | `status` ∈ active, disabled |
| `connected_platforms` | Verified platform identity (SteamID64), public profile fields, `game_details_status` (unknown/accessible/empty/private/error), `last_synced_at` | unique (`platform`, `external_user_id`): one Steam account → one user; unique (`user_id`, `platform`) |
| `user_sessions` | Server-side sessions; **only SHA-256 of the cookie token** | unique `token_hash`; `expires_at`, `revoked_at` |
| `user_privacy_settings` | `contribute_to_global_training`, `allow_scheduled_sync` | PK `user_id` |

### Catalogue and taxonomy

| Table | Purpose | Key constraints |
|---|---|---|
| `games` | Canonical game shared by all users; `merged_into_game_id` for duplicate resolution | no self-merge |
| `external_game_ids` | Steam AppID (first identifier) and future IGDB/RAWG ids | **unique (`provider`, `external_id`)**: prevents duplicate games |
| `game_sources` | Latest fetch per game and provider: status ok/not_found/error, `fetched_at`, `mapping_version` | unique (`game_id`, `provider`) |
| `game_review_summaries` | Review count, % positive and label per source | PK (`game_id`, `source`) |
| `feature_categories` | Taxonomy categories with `scoring_group` (spec §16 weights) | unique `slug` |
| `game_features` | Hierarchical canonical features: name, category, parent, description, synonyms, status, timestamps | unique `slug`; no self-parent |
| `provider_tags` | Raw provider vocabulary (Steam tag 1702 "Crafting", category 2 "Single-player") | unique (`provider`, `kind`, `external_id`) |
| `game_provider_tags` | Raw tags as imported per game, with vote weight and rank | PK (`game_id`, `provider_tag_id`) |
| `provider_tag_mappings` | Raw tag → canonical feature, with confidence and mapping version; older versions `superseded` | unique (provider, kind, tag, feature, version) |
| `game_feature_values` | Derived value (0–1) and confidence (0–1) per (game, feature, source), with mapping version and JSON evidence | PK (`game_id`, `feature_id`, `source`); range checks |

### Gaming activity

| Table | Purpose | Key constraints |
|---|---|---|
| `user_library` | Current state per (user, platform, game): `source` steam_import/manual, playtime in **integer minutes** (NULL = unknown for manual entries), 2-week minutes, `last_played_at`, `removed_at` | unique (`user_id`, `platform`, `game_id`); non-negative checks |
| `user_feedback` | Explicit satisfaction rating, Loved 2 … Hated −2 (spec §18). Owned or played elsewhere | unique (`user_id`, `game_id`); range check |
| `playtime_snapshots` | **Append-only**, platform-reported values: written on first import and on any change | index (`library_entry_id`, `captured_at`) |
| `achievement_summaries` | Achieved/total for recently played games | status ok/no_stats/unavailable |
| `library_sync_runs` | Import attempts (trigger, status, counts, error code) | **partial unique index: one queued/running run per user** |

Concurrency: new canonical games are created under a transaction-level advisory lock
and re-checked after acquiring it, with `external_game_ids` uniqueness as a backstop.
An integration test runs six concurrent importers of the same 40 games and checks that
no duplicates appear.

### Profiles and recommendations (Stage 3, ADR-0016)

| Table | Purpose | Key constraints |
|---|---|---|
| `user_preferences` | Manual preference value (−1…1) and/or hard exclusion per feature. Overrides inferred values | PK (`user_id`, `feature_id`); value range; value or exclusion required |
| `user_preference_events` | **Append-only** log of manual changes (old and new value or exclusion) | index (`user_id`, `created_at`) |
| `profile_runs` | One profile computation: parameter version and full parameters (JSONB), input counts, overall confidence | index (`user_id`, `created_at`) |
| `user_feature_preferences` | Current inferred value and confidence per feature, with historical, recent and satisfaction components, attributed minutes and evidence games | PK (`user_id`, `feature_id`); value and confidence range checks |
| `user_feature_preference_history` | Inferred values that changed in a run (NULL value = no longer inferred) | PK (`profile_run_id`, `feature_id`) |
| `recommendation_runs` | One ranked list per category: algorithm, parameters, data state (ok/incomplete/unavailable), counts, note | category and data-state checks; index (`user_id`, `category`, `created_at`) |
| `recommendation_items` | Ranked games with category score, match, backlog and trend scores, confidence, group scores, contributions, reasons, candidate sources | PK (`run_id`, `rank`); unique (`run_id`, `game_id`) |
| `game_prices` | Steam storefront price per country (final, original, discount, formatted) | PK (`game_id`, `country_code`) |
| `game_discovery_sources` | Why a game entered the catalogue (tag query, charts) | PK (`game_id`, `source`) |
| `player_count_samples` | Concurrent players per sampling pass (raw, kept 60 days) | PK (`game_id`, `sampled_at`) |
| `player_count_daily` | Daily average and maximum players and sample count: the input of trend scoring | PK (`game_id`, `day`) |

Contributions, reasons and group scores are JSONB because their shape follows the
engine version. Every run stores the parameters that produced it, so old runs stay
interpretable. Historical runs are never deleted when a profile changes (spec §26).

### Behaviour and feedback (Stage 4, ADR-0017, [docs/BEHAVIOUR.md](docs/BEHAVIOUR.md))

| Table | Purpose | Key constraints |
|---|---|---|
| `behaviour_events` | **Append-only** log: impressions, clicks, game page views, store visits, feedback toggles, satisfaction, question actions, playtime changes, preference changes, each with its exposure context (run, category, position, model version, surface) | type and surface checks; unique (`user_id`, `idempotency_key`) where the key is set; trigger rejects updates except references set to NULL; indexes on (`user_id`, `occurred_at`), (`event_type`, `occurred_at`), `game_id`, `recommendation_run_id` |
| `user_game_reactions` | Current feedback per game: like or dislike, favourite, saved, dismissal (and its reason), already played. Rows with nothing set are deleted | PK (`user_id`, `game_id`); a reason only with "not interested" |
| `satisfaction_prompts` | Post-play question state: times shown, last shown, snoozed until, declined, answered | PK (`user_id`, `game_id`) |

### Model registry (Stage 4, ADR-0018, [docs/COLLABORATIVE.md](docs/COLLABORATIVE.md))

| Table | Purpose | Key constraints |
|---|---|---|
| `training_runs` | One pipeline run: status (running, succeeded, skipped, failed), trigger, dataset statistics, decision text | status check |
| `model_versions` | A trained model: algorithm, parameters, dataset statistics, metrics, artifact path and SHA-256, status (candidate, deployed, rejected, retired) | unique `version`; **at most one deployed per kind** (partial unique index) |
| `evaluation_results` | Every metric of every algorithm on every split of a run | unique (`training_run_id`, `algorithm`, `split`, `metric`) |
| `model_deployment_history` | Append-only deploy and rollback log, with the previous version and the reason | action check |
| `account_deletions` | A timestamp per deleted account, no identifier. Triggers a retrain | — |
| `player_count_passes` | Stage 6: each sampling pass of the player-count source (tracked, sampled, no data, failed, error code). Freshness and reliability gates for trending | index (`started_at`) |
| `game_completion_times` | Stage 6: time to beat per game and source (hastily / normally / completely seconds, submissions, IGDB id, `fetched_at`). All-NULL rows record "asked, no data" | PK (`game_id`, `source`) |
| `model_monitoring_reports` | Stage 5: one row per day and window with production metrics (satisfaction rate and coverage, negative feedback, calibration, online NDCG/precision, coverage, diversity, training failures, drift) and alerts | unique (`day`, `window_days`) |

Stage 5 also added `training_runs.report` (the full evaluation report),
`model_versions.feature_schema_version`, and the satisfaction model's id and
predictions on recommendation runs and items ([docs/SATISFACTION.md](docs/SATISFACTION.md)).

### Retention (Stage 6)

A daily `prune_data` job deletes recommendation runs that were never shown (no
behaviour event refers to them) after 24 hours and all other runs after 90 days (the
latest per player and category is always kept). Each feedback click rebuilds three
lists, so most runs are replaced before anyone sees them; without the 24-hour rule
`recommendation_items` grew by about 270 MB per hour in the 100-player load test. It also deletes behaviour events older than 730 days
and monitoring reports older than 400 days (all configurable; 0 keeps forever). Player-count
samples are kept 60 days; daily aggregates are kept.

## Planned schema (spec §26, later stages)

All tables named in spec §26 now exist. The satisfaction model (Stage 5) uses the
registry with `kind = 'satisfaction'`.

`pgvector` is not installed. If vector similarity becomes useful, switch the
image to `pgvector/pgvector:pg18-trixie`. It uses the same Debian base and
collation, so the data volume stays compatible.

## Backups and recovery

See [DEPLOYMENT.md § Backups](DEPLOYMENT.md#backups).
