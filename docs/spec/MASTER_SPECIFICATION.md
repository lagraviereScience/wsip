# WHAT DO YOU WANT TO PLAY?
# Master Development Specification and Implementation Prompts

> Authoritative requirements document for this project. Stored verbatim as supplied
> by the product owner (document version 1.0). Part XI's six stage prompts are
> stored separately in [`prompts/`](prompts/) as they are received.
> Known gaps and open questions are tracked in [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md).

**Project:** What Do You Want to Play?
**Document version:** 1.0
**Product type:** Public multi-user web application
**Initial platform:** Steam
**Primary objective:** Personalised video game recommendations using behavioural analysis and specialised machine-learning models.

---

# PART I — MASTER PROMPT

## 1. Your role

You are a senior full-stack software engineer, software architect, database designer and machine-learning engineer.

Your task is to design, implement, test and document a production-oriented web application called **What Do You Want to Play?**

You have access to the project's source code environment and are expected to modify files, execute commands, install dependencies, run tests and implement working functionality.

Do not merely produce architectural suggestions or code snippets. Implement the application.

Work incrementally, maintaining a working application throughout development.

You must follow the development stages described in this document in their specified order.

## 2. Product vision

What Do You Want to Play? analyses a player's Steam account and gaming history to build a detailed gamer profile.

It uses this profile to generate three personalised recommendation lists:

1. **Games you own that you should play.**
2. **Games you don't own that you should play.**
3. **Trending games that you should play.**

The recommendation engine must understand individual gaming preferences, learn from player behaviour and progressively improve its recommendations.

The application must prioritise predicting actual player satisfaction rather than maximising clicks, popularity or gaming time.

## 3. Confirmed product decisions

These decisions are requirements, not suggestions.

| Area | Decision |
|---|---|
| Target users | Anyone with a Steam account |
| Application model | Public website |
| User management | Multi-user |
| Authentication | Proper Steam OpenID 2.0 authentication |
| Initial platform | Steam |
| Future platforms | Architecture must support additional gaming platforms |
| Profile privacy | Users must make their Steam game details public |
| Recommendations | Automatic |
| User customisation | Users can manually adjust preferences and exclude tags |
| Recommendation philosophy | Mostly recommend games similar to existing preferences |
| AI approach | Specialised machine-learning recommendation system |
| General-purpose LLM | Not required for core functionality |
| Model training | Daily batch training |
| Learning strategy | Global model plus individual personalisation |
| Feedback | Explicit and passive behavioural tracking |
| Optimisation objective | Explicit player satisfaction, supported by playtime |
| Hosting | Existing Linux server |
| Deployment | Docker Compose |
| Initial target | Up to 100 concurrent web users |
| AI inference | CPU-first; GPU acceleration only where justified |
| Initial interface language | English |
| Future interface languages | Multilingual |

## 4. Fundamental architecture principle: no general-purpose LLM dependency

This application does NOT need a general-purpose language model to function.

Do not introduce OpenAI, Anthropic, Ollama, llama.cpp or other general-purpose LLM dependencies for core recommendation functionality.

The intelligence of the application must come from specialised algorithms trained on gaming data.

The primary technologies to evaluate are:

- Content-based filtering.
- Collaborative filtering.
- Matrix factorisation.
- Hybrid recommendation algorithms.
- Supervised satisfaction prediction.
- Learning-to-rank.
- Behavioural modelling.

Potential Python libraries:

- LightFM.
- implicit.
- LightGBM.
- NumPy.
- SciPy.
- scikit-learn.
- pandas.

Do not automatically install every library. Select the minimum set required for the implemented functionality.

The recommendation system must work from the first release, even when there is insufficient collective data to train a global model.

---

# PART II — TECHNICAL ARCHITECTURE

## 5. Initial technology stack

Use the following architecture unless a demonstrable technical incompatibility requires an alternative. Document any proposed change before implementing it.

### Frontend

- Next.js.
- React.
- TypeScript.
- Tailwind CSS.
- A maintainable component library.
- Responsive desktop and mobile design.

### Backend

- Python.
- FastAPI.
- Pydantic.
- SQLAlchemy 2.
- Alembic.
- REST API.

### Database

- PostgreSQL.
- Optional pgvector extension if vector similarity becomes useful.
- Redis for caching and background job coordination.

PostgreSQL should be the primary source of truth.

Avoid adding a separate vector database unless profiling demonstrates a real need.

### Background processing

- Celery.
- Redis.
- Periodic scheduler.

Use background processing for Steam synchronization, metadata ingestion, profile calculation, recommendation generation and model training.

### Machine learning

- Python.
- LightFM and/or implicit for collaborative filtering.
- LightGBM for satisfaction prediction and later ranking.
- scikit-learn for preprocessing, calibration and evaluation.

### Infrastructure

- Linux server.
- Docker Compose.
- Existing Traefik reverse proxy, where appropriate.
- HTTPS.
- Persistent Docker volumes.
- Automated database backups.
- Health checks.
- Centralised logging.

## 6. Architectural style

Use a modular monolith initially.

Do not introduce Kubernetes or distributed microservices for the initial deployment.

Keep logical modules independent so that they can be separated into dedicated services later.

Recommended modules:

```text
frontend/
backend/
  app/
    api/
    core/
    models/
    schemas/
    repositories/
    services/
    integrations/
      steam/
      game_metadata/
      trends/
    recommendations/
      features/
      profiling/
      candidate_generation/
      ranking/
      evaluation/
    machine_learning/
      datasets/
      training/
      models/
      registry/
    workers/
    database/
    tests/
```

Adapt this structure if needed, but retain clear separation of responsibilities.

## 7. Linux server constraints

The production application will run on an existing Linux server with approximately:

- 56 CPU cores as reported.
- 64 GB RAM.
- NVIDIA RTX 4060 Ti with 16 GB VRAM.

These resources are shared with other services.

Design the application so it does not monopolise CPU, RAM or GPU resources.

Initial machine-learning workloads should be tested on CPU.

Do not assume that GPU acceleration will improve performance at this scale.

The initial target is up to 100 concurrent web users, not 100 simultaneous machine-learning training jobs or inference requests.

Use queues and controlled worker concurrency.

---

# PART III — GAME DATA AND TAXONOMY

## 8. Unified game catalogue

The application must maintain a central game catalogue shared by every user.

Do not create separate game records for each user.

Every game must have a canonical internal identifier.

Support external identifiers such as:

- Steam AppID.
- IGDB ID.
- RAWG ID.
- Future platform-specific identifiers.

Store source information and external identifiers separately from the canonical game record.

The game catalogue must support multiple platforms in the future.

## 9. Metadata ingestion

Steam is the first integration.

Additional sources should enrich the shared catalogue.

Potential sources:

| Provider | Intended purpose |
|---|---|
| Steam Web API | User libraries and gaming activity |
| Steam Store | Game descriptions and metadata |
| IGDB | Structured game information |
| RAWG | Additional game metadata |
| SteamCharts | Player-count trends |
| SteamDB | Historical statistics and trends |
| HowLongToBeat | Estimated game duration |
| OpenCritic | Review information |

Do not assume that every provider offers an unrestricted public API.

Before implementing each provider, verify:

- API availability.
- Authentication requirements.
- Rate limits.
- Commercial usage rights.
- Data storage and caching rights.
- Attribution requirements.
- Restrictions on redistribution.

Do not scrape websites without verifying that the activity is authorised by their terms.

SteamDB and SteamCharts integrations must use an authorised data-access method. If no suitable method is available, implement a disabled provider adapter and document the limitation.

IGDB integration requires particular attention to commercial usage conditions. The project is a public website, and the right to use its data must be established before production use.

If a provider cannot be used legally or reliably, the application must continue functioning without it.

## 10. Canonical game taxonomy

This is a core product requirement.

Do not rely exclusively on the original Steam tags.

Build and maintain a canonical internal taxonomy by combining Steam tags, IGDB metadata and other authorised sources.

The taxonomy must be hierarchical.

Initial feature categories:

### Genres and themes

Examples: RPG. Action RPG. FPS. Strategy. Simulation. Horror. Survival. Racing. Sports. Roguelike.

### Gameplay mechanics

Examples: Crafting. Exploration. Base building. Resource management. Combat. Stealth. Character progression. Trading. Automation. Farming.

### Game modes

Examples: Singleplayer. Online multiplayer. Local multiplayer. Co-op. Competitive. PvP. PvE.

### Game structure

Examples: Open world. Linear. Sandbox. Procedural generation. Mission-based. Level-based. Persistent world.

### Pace and complexity

Examples: Relaxed. Tactical. Fast-paced. Hardcore. Casual. Complex management. Survival-oriented.

The taxonomy must support additional categories and features without database redesign.

Each feature must have:

- Unique identifier.
- Name.
- Category.
- Parent feature, where applicable.
- Description.
- Synonyms.
- Status.
- Creation and update timestamps.

Provider tags must be mapped to canonical features.

For every mapping, store:

- Provider.
- Original tag.
- Canonical feature.
- Mapping confidence.
- Mapping version.

Never count both a parent feature and all its children as independent evidence in the same calculation.

Unknown information must be represented as unknown, not as an explicit absence.

Use feature confidence to reflect metadata reliability.

Maintain data provenance.

---

# PART IV — PLAYER PROFILING

## 11. Player profile

Each user must have a continuously evolving gamer profile.

The profile must contain:

- Genre preferences.
- Tag preferences.
- Gameplay preferences.
- Game-mode preferences.
- Historical gaming interests.
- Recent gaming interests.
- Engagement patterns.
- Explicit preferences.
- Explicit dislikes.
- Excluded categories.
- Profile confidence.

Each preference must have:

- Numerical value.
- Confidence.
- Origin: inferred or manually configured.
- Supporting evidence.
- Last update timestamp.

Use preference values between -1 and +1:

| Value | Interpretation |
|---|---|
| +1 | Strong preference |
| +0.5 | Moderate preference |
| 0 | Neutral or unknown |
| -0.5 | Moderate dislike |
| -1 | Strong dislike |

Preference confidence must be separately stored between 0 and 1.

Manual preferences take precedence over automatically inferred preferences.

Explicit tag exclusions must be hard constraints, not merely negative scoring factors.

## 12. Playtime analysis

Maintain separate historical and recent activity metrics.

Where data is available, collect:

- Lifetime playtime.
- Last two weeks of playtime.
- Last played date.
- Historical snapshots.
- Estimated activity between snapshots.

Store playtime in minutes internally.

Use logarithmic transformation for lifetime playtime to avoid allowing extremely large playtime values to dominate.

A proposed lifetime normalisation is:

```text
H_total = ln(1 + min(hours, 1000)) / ln(1001)
```

A proposed recent-playtime transformation:

```text
H_recent = 1 - exp(-hours_last_30_days / 8)
```

A proposed recency feature:

```text
R = 2 ^ (-days_since_last_play / 90)
```

Treat these as configurable starting parameters.

The application must not invent historical activity that Steam does not provide.

Store snapshots from the moment the user first connects.

When estimating playtime between snapshots, clearly distinguish estimated activity from directly reported Steam values.

## 13. Tag-based playtime calculations

Calculate gaming time by canonical game feature.

If a game has multiple tags within the same category, distribute its attributable playtime across those tags to prevent artificial multiplication.

Maintain separate calculations for:

- Lifetime tag exposure.
- Recent tag exposure.
- Historical tag exposure.
- Feature preference inferred from satisfaction.
- Feature preference inferred from behaviour.

Do not confuse time played with satisfaction.

A game may have substantial playtime without representing a positive satisfaction signal.

---

# PART V — MATHEMATICAL RECOMMENDATION ENGINE

## 14. Game representation

Each game must be represented through a feature vector:

```text
G_i = [x_i1, x_i2, ..., x_in]
```

Where feature values are between 0 and 1, or null when unknown.

Feature values must represent the strength or presence of a canonical feature.

## 15. Player representation

Each user must have a preference vector:

```text
P_u = [p_u1, p_u2, ..., p_un]
```

With:

```text
-1 <= p_uf <= 1
```

A separate confidence vector must be maintained:

```text
C_u = [c_u1, c_u2, ..., c_un]
```

With:

```text
0 <= c_uf <= 1
```

Do not mix preference strength with confidence.

## 16. Initial content compatibility

Use the following category weights as configurable initial values:

| Feature category | Weight |
|---|---:|
| Genres and themes | 25% |
| Gameplay mechanics | 30% |
| Game modes | 20% |
| Game structure | 15% |
| Pace and complexity | 10% |

The initial content-based compatibility must:

- Reward games matching positive preferences.
- Penalise features explicitly disliked by users.
- Ignore unavailable metadata.
- Account for feature confidence.
- Avoid double-counting hierarchical tags.
- Normalise scores to a 0–100 scale.

Implement the initial mathematical baseline as documented and test it with synthetic fixtures.

Do not treat a missing game feature as confirmed absence.

A user should not be penalised for metadata that has not been collected.

Expose category-level compatibility contributions for explainability.

These weights must be configurable and subsequently evaluated against observed satisfaction.

## 17. Collaborative filtering

Implement collaborative filtering when sufficient user interaction data exists.

Evaluate:

- LightFM hybrid recommendation.
- implicit ALS or BPR.

The model must learn similarities between users and games.

Ownership alone must not be treated as proof that a player enjoys a game.

Clicks alone must not be treated as proof of satisfaction.

Use appropriate signal weighting and distinguish preference evidence from ownership and exposure.

## 18. Satisfaction prediction

The primary prediction target is:

```text
P_sat(user, game) =
Probability that the user will report positive satisfaction
```

The result must be between 0 and 1.

Explicit post-play satisfaction must be the primary training label.

Initial feedback options should support:

- Loved it.
- Liked it.
- Neutral.
- Disliked it.
- Hated it.

Also support a simple question:

"Did you enjoy this game?"

Passive signals should support the model but must not replace explicit satisfaction labels.

Distinguish:

- Satisfaction prediction.
- Engagement prediction.
- User interest.
- Prediction confidence.

Use LightGBM as an initial supervised model candidate.

Start with a clearly documented baseline.

Evaluate binary classification and ordinal satisfaction modelling where data volume allows.

A model output must not be presented as a calibrated satisfaction probability unless it has been calibrated and evaluated.

The application must gracefully fall back to content-based recommendations until sufficient training data exists.

## 19. Recommendation candidate generation

Use a union of candidates from:

1. Content-based filtering.
2. Collaborative filtering.
3. Similarity to favourite games.
4. Category-specific discovery sources.

Apply ownership constraints and explicit exclusions.

Do not recommend games already owned in the unowned categories.

Do not recommend games already owned in the trending category unless the user has explicitly requested owned-game discovery there.

Apply user exclusions before ranking.

Candidate generation and final ranking must be separate components.

## 20. Three recommendation categories

### 20.1. Games owned by the user

Primary objective: recommend games the user owns and is likely to enjoy.

Prioritise:
- High predicted satisfaction.
- Unplayed games.
- Barely played games.
- Backlog opportunities.
- Games matching recent interests.

Initial backlog score:

```text
U = exp(-total_playtime_hours / 20)

D = 1 - exp(-days_since_last_play / 90)

Backlog = 0.65 * U + 0.35 * D
```

For never-played games, use a backlog value of 1.

Initial ranking:

```text
Owned_score = 0.85 * satisfaction_score
            + 0.15 * backlog_score
```

Both inputs must be on a 0–100 scale.

These weights are configurable and must be tested.

Do not automatically recommend heavily played games as backlog items.

### 20.2. Games not owned by the user

Primary objective: recommend games the player is likely to enjoy but does not own.

Initial ranking:

```text
Unowned_score = predicted_satisfaction_score
```

Price, discounts and review information should be presented separately.

Support user-controlled filters for:

- Maximum price.
- Free-to-play.
- Minimum review rating.
- Release period.
- Multiplayer requirements.

### 20.3. Trending games

Trending status must reflect actual popularity growth rather than absolute popularity alone.

Use permitted historical player-count sources.

Potential metrics:
- Seven-day average concurrent players.
- Previous 28-day baseline.
- Relative player growth.
- Growth acceleration.
- Category-relative performance.

An initial calculation:

```text
growth_7 = ln(
    (average_players_last_7_days + epsilon)
    /
    (average_players_previous_28_days + epsilon)
)

acceleration = growth_7 - previous_comparable_growth
```

Normalise metrics through percentiles.

Initial trend score:

```text
Trend_score =
    0.70 * percentile(growth_7)
    + 0.30 * percentile(acceleration)
```

Initial trending ranking:

```text
Trending_score =
    0.80 * satisfaction_score
    + 0.20 * trend_score
```

Require minimum data quality and configurable eligibility thresholds.

Do not label a game trending solely because it has many players.

If trend data is unavailable, do not fabricate a trend score.

---

# PART VI — BEHAVIOURAL DATA AND LEARNING

## 21. Event-tracking system

Implement a structured, append-only behavioural event system.

Track:

- Recommendation impressions.
- Recommendation position.
- Clicks.
- Game detail views.
- Steam Store visits.
- Favourites.
- Likes.
- Dislikes.
- Explicit dismissals.
- "Already played" actions.
- "Save for later" actions.
- Excluded tags.
- Satisfaction ratings.
- Steam playtime changes.

Each event should include:

- Event ID.
- User ID.
- Game ID.
- Event type.
- Timestamp.
- Recommendation ID, where applicable.
- Recommendation category.
- Position.
- Model version.
- Relevant metadata.
- Exposure context.

Record actual visibility, not merely the fact that a recommendation was generated.

Avoid duplicate events using idempotency keys where appropriate.

## 22. Signal interpretation

Do not treat every interaction as equivalent.

| Signal | Interpretation |
|---|---|
| Explicit satisfaction rating | Primary satisfaction evidence |
| Favourite | Strong positive interest |
| Explicit dislike | Negative preference evidence |
| "Not my type" | Negative feature preference evidence |
| Click | Weak interest |
| Store visit | Weak interest |
| Playtime increase | Supporting engagement evidence |
| Repeated play | Supporting engagement evidence |
| No interaction | Unknown |

Distinguish dislike of a game from rejection due to price, timing or an existing purchase.

A user dismissing a game because it is too expensive should not teach the model that they dislike its gameplay.

## 23. Global and individual learning

Maintain:

**Global model**
- Learns from eligible collective behavioural data.
- Identifies relationships between games and players.
- Produces collaborative recommendations.

**Individual profile**
- Incorporates explicit feedback.
- Maintains preferences and exclusions.
- Updates from observed gaming activity.
- Overrides conflicting global recommendations where necessary.

Allow users to opt out of contributing their behavioural data to global model training.

Users must not have access to other users' private gaming profiles or raw personal event histories.

## 24. Daily training

The global models must be evaluated and trained through a daily batch pipeline.

The pipeline must:

1. Collect eligible events.
2. Validate and prepare datasets.
3. Generate features.
4. Train the collaborative model.
5. Train the satisfaction prediction model.
6. Evaluate performance.
7. Compare with the deployed model.
8. Deploy only if quality requirements are met.
9. Retain earlier versions for rollback.

Daily execution does not automatically mean daily deployment.

If there is insufficient new data or the new model performs worse, retain the existing model.

Individual manual settings must take effect immediately.

## 25. Model evaluation

Primary metric:

- Explicit player satisfaction rate.

Supporting metrics:

- Negative feedback rate.
- Satisfaction by recommendation category.
- Sustained playtime after recommendations.
- NDCG@5.
- Precision@5.
- Satisfaction calibration.
- Recommendation coverage.
- Diversity.

Always report feedback coverage with satisfaction rate.

Avoid evaluating only users who voluntarily submit feedback without acknowledging selection bias.

Use chronological training/validation/test splits to avoid future-information leakage.

Use controlled A/B testing when the application has sufficient traffic.

---

# PART VII — DATABASE

## 26. Initial relational schema

Implement and document a normalised PostgreSQL schema.

The following entities are required:

### Users
- users.
- connected_platforms.
- user_preferences.
- user_privacy_settings.

### Game catalogue
- games.
- external_game_ids.
- game_sources.
- game_features.
- game_feature_values.
- provider_tag_mappings.

### Gaming activity
- user_library.
- playtime_snapshots.
- achievements, if supported.

### Recommendation system
- recommendation_runs.
- recommendation_items.
- user_feedback.
- behaviour_events.

### Machine learning
- model_versions.
- training_runs.
- evaluation_results.
- model_deployment_history.

Add indexes, unique constraints and foreign keys.

Use migrations.

Do not delete historical events simply because a user's inferred profile has changed.

Store timestamps in UTC.

Store Steam playtime internally in integer minutes.

Use suitable JSON fields only for genuinely variable metadata, not as a replacement for relational modelling.

---

# PART VIII — STEAM INTEGRATION AND SECURITY

## 27. Steam authentication

Implement proper Steam OpenID 2.0 authentication.

Use Steam's provider endpoint:

```text
https://steamcommunity.com/openid/
```

Use an established, maintained OpenID library.

Validate the OpenID response server-side.

Validate the claimed identity and extract the SteamID64 only after verification.

Implement:
- Nonce/replay protection.
- Return URL validation.
- State/CSRF protection.
- Secure session management.
- HttpOnly cookies.
- Secure cookies over HTTPS.
- SameSite policy.
- Session expiration.
- Account linking safeguards.

Steam passwords must never pass through or be stored by this application.

Official Steam authentication documentation:

https://partner.steamgames.com/doc/features/auth

## 28. Steam library access

OpenID authenticates the Steam user but does not automatically grant access to private gaming data.

Use the supported Steam Web API methods.

Potential initial endpoints:

- IPlayerService/GetOwnedGames.
- IPlayerService/GetRecentlyPlayedGames.
- ISteamUser/GetPlayerSummaries.
- ISteamUserStats/GetPlayerAchievements, where practical and available.

The exact response fields and access conditions must be checked against current documentation before implementation.

The backend must securely store its Steam Web API key.

Never expose API credentials to the browser.

Owned-game retrieval must verify that the user's game details are visible.

The user has explicitly agreed to make Steam game details public.

If data cannot be retrieved, show a clear onboarding explanation and do not generate a misleading profile.

Distinguish an inaccessible library from a genuinely empty library whenever the available API responses allow this distinction.

Do not assume that Steam provides complete historical playtime.

Record snapshots after initial connection.

Official references:

https://partner.steamgames.com/doc/webapi_overview

https://partner.steamgames.com/doc/webapi/iplayerservice

https://partner.steamgames.com/doc/webapi_overview/auth

## 29. Multi-platform compatibility

Design a platform adapter interface.

Each adapter should implement the available equivalents of:

- Authentication.
- External user identification.
- Library retrieval.
- Playtime retrieval.
- Activity retrieval.
- Platform metadata.

The recommendation engine must consume platform-independent internal data.

Steam must be the only fully implemented platform initially.

---

# PART IX — APPLICATION USER EXPERIENCE

## 30. Initial navigation

The application should provide:

1. Dashboard.
2. My Gamer Profile.
3. My Game Library.
4. Games I Should Play.
5. Games I Should Buy.
6. Trending Games.
7. Settings.

## 31. Dashboard

The dashboard should answer:

"What should I play right now?"

Display:
- Top recommendations.
- Brief gamer profile summary.
- Recent gaming activity.
- Last synchronization.
- Interesting backlog games.
- Relevant trending games.

## 32. Gamer profile

Display:
- Genre preferences.
- Feature and tag preferences.
- Historical versus recent interests.
- Singleplayer/multiplayer balance.
- Most influential games.
- Confidence levels.
- Manual preferences.

Users must be able to adjust preference values and exclude tags.

Clearly distinguish inferred and manually configured preferences.

## 33. Recommendation cards

Each game card should display:

- Artwork.
- Game title.
- Recommendation category.
- Predicted satisfaction, where sufficiently reliable.
- Recommendation confidence.
- Relevant tags.
- Reasons for recommendation.
- Ownership status.
- Steam Store link.
- Price and review information where available.

Never present an uncalibrated algorithm score as a precise probability of enjoyment.

Provide a breakdown explaining why the game was recommended.

---

# PART X — PRIVACY, SECURITY AND OPERATIONS

## 34. Privacy

Implement appropriate privacy-by-design controls.

Requirements:

- Users can disconnect Steam.
- Users can delete their accounts.
- Users can request deletion of personal data.
- Users can opt out of global behavioural training.
- Private user profiles must not be publicly accessible.
- Raw behavioural events must not be exposed to other users.
- Global training must use appropriately pseudonymised data.
- Access to personal data must be restricted.

The application must support data export and account deletion workflows.

Model lifecycle procedures must document how user deletion and training datasets are handled. Do not claim perfect machine unlearning if the underlying training process does not support it.

Prepare privacy documentation and identify the legal requirements that must be reviewed before public launch.

## 35. Security

Implement:
- Input validation.
- SQL injection protection.
- XSS protection.
- CSRF protection.
- Authentication throttling.
- API rate limiting.
- Secure secret handling.
- Secure container configuration.
- Least-privilege database access.
- HTTPS.
- Dependency vulnerability checks.

Do not expose:
- PostgreSQL.
- Redis.
- Internal worker interfaces.
- Internal recommendation service.
- Administrative endpoints.

## 36. Observability

Monitor:
- CPU.
- RAM.
- GPU usage where applicable.
- Disk usage.
- Database health.
- Redis health.
- Queue length.
- Worker failures.
- Steam API failures.
- Provider rate limits.
- Recommendation generation latency.
- Training execution.
- Model performance.

Implement Docker health checks and restart policies.

Back up PostgreSQL regularly.

Document recovery procedures.

---

# PART XI — DEVELOPMENT AND IMPLEMENTATION PROMPTS

The application must be developed through the following six stages.

Do not attempt to implement everything in a single operation.

Each stage must leave the application in a working condition and produce documentation for the next stage.

The stage prompts are stored in [`prompts/`](prompts/).
