# PROMPT 7 — Additional changes: AI_GRADE configuration and deployment tutorial

(Requested by the owner after Stage 6. Implemented in ADR-0020, ADR-0021,
docs/SCORING_MODES.md, docker-compose.yml, compose.dev.yaml, .env.example and
tutorial.md.)

The core application has been implemented. I want two additional improvements.
Before implementing them, inspect the current repository, configuration, Docker Compose files, machine-learning architecture and documentation.
These changes must integrate into the existing application without unnecessarily rewriting working components.
Do not commit changes automatically.

## PART 1 — AI_GRADE: Switch Between Machine Learning and Classic Scoring

### 1. Objective

I want to be able to choose between two recommendation-scoring modes through a single environment variable in the application's `.env` file.
The variable must be called:

```
AI_GRADE=TRUE
```

It must accept only `TRUE` or `FALSE`, case-insensitively.
The default should be `TRUE` if not otherwise specified.
An invalid value must cause a clear configuration error rather than silently selecting an unexpected mode.
This is a deployment-level configuration, not an individual user's preference.
It applies globally to all application users.
Changing the variable should require the appropriate application services to be recreated or restarted.

### 2. Mode A: AI_GRADE=TRUE

When enabled, use the existing locally developed machine-learning recommendation architecture.
This includes the relevant implemented components:

* Collaborative filtering.
* Locally trained satisfaction prediction model.
* Learned recommendation ranking, if implemented and sufficiently trained.
* Existing individual personalisation.
* Global model learning.

Continue using the existing specialised machine-learning implementation.
Do not introduce general-purpose LLMs.
The application must respect model availability, confidence and evaluation status.
If a model is unavailable, insufficiently trained or invalid, use the existing documented fallback behaviour rather than failing the entire recommendation system.

### 3. Mode B: AI_GRADE=FALSE

When disabled, the application must use exclusively deterministic, conventional mathematical recommendation scoring.
This is a genuine non-machine-learning recommendation mode.
Disable the execution of:

* Collaborative filtering predictions.
* Learned satisfaction prediction.
* Learned ranking models.
* Other trained recommendation inference.

Do not load these models unnecessarily.
Skip scheduled model-training operations while this mode is active, to avoid consuming unnecessary CPU and memory.
However, continue collecting eligible behavioural events, subject to user privacy settings, so the data remains available when machine-learning mode is re-enabled.
The application must continue supporting all three recommendation categories.

#### Classic scoring methodology

Use the existing documented mathematical scoring architecture.
It should consider:

* Genre compatibility.
* Canonical game features.
* Gameplay mechanics.
* Game modes.
* Game structure.
* Pace and complexity.
* Total playtime.
* Recent playtime.
* Last played date.
* Manually configured preferences.
* Explicit negative preferences.
* Excluded tags.

Use configurable coefficients and weights.
Use the existing feature-vector and player-preference calculations wherever possible.
The classic engine must remain deterministic: given identical input data and configuration, it should produce identical scores and ranking.
Do not introduce random scoring or arbitrary LLM-generated explanations.
All explicit exclusions must remain hard constraints.

#### Category-specific calculations

Retain the existing category-specific mathematical formulas:

* Owned games: compatibility plus backlog prioritisation.
* Unowned games: compatibility.
* Trending games: compatibility plus validated trend score.

Do not remove the historical, recent-playtime or tag-analysis functionality.

### 4. Architecture requirements

Implement a clearly separated recommendation mode selection.
For example:

```
RecommendationService
    |
    |-- AI_GRADE = TRUE
    |       |
    |       |-- MachineLearningRecommendationEngine
    |
    |-- AI_GRADE = FALSE
            |
            |-- ClassicRecommendationEngine
```

Use the actual existing architecture where appropriate.
The mode selection must occur centrally, not through scattered checks throughout the application.
Both engines must use the same:

* Game catalogue.
* Canonical taxonomy.
* Player data.
* Ownership data.
* Manual preferences.
* Explicit exclusions.
* Candidate eligibility rules.

Only the scoring and ranking implementation should differ.
The engines must return a common recommendation result structure so the frontend does not need separate implementations for each mode.

### 5. Dashboard and other recommendation functionality

The `AI_GRADE` setting must also apply to:

* Dashboard recommendations.
* Games I Should Play.
* Games I Should Buy.
* Trending Games.
* Suggest Another One functionality.

No page or recommendation endpoint should accidentally bypass the selected scoring mode.
Cached recommendations must be associated with their scoring mode and model/configuration version.
When the application changes from one mode to the other, invalidate or regenerate incompatible cached recommendations.
The application must never display an AI-generated score while operating in classic mode.
Likewise, it must never display a classic score while presenting it as a trained satisfaction prediction.

### 6. Model training and switching modes

When `AI_GRADE=FALSE`:

* Skip unnecessary model-training jobs.
* Do not load machine-learning models for recommendation inference.
* Retain eligible collected events.
* Keep model artefacts intact.
* Keep model registry information intact.
* Do not delete previously trained models.

When `AI_GRADE=TRUE` again:

* Restore normal model-loading and inference behaviour.
* Resume scheduled model training.
* Validate model availability before using it.
* Continue using previous valid models where appropriate.

Changing mode must not require database deletion or data migration unless a genuine technical reason exists.

### 7. Configuration and observability

Expose the currently active scoring mode in an appropriate application health or administrative status endpoint.
Do not expose sensitive model information.
Administrative logs should clearly indicate whether the active mode is:

* `AI`
* `CLASSIC`

Make it straightforward to identify which engine generated a particular recommendation.
Include scoring mode and relevant model/configuration version in recommendation metadata.

### 8. Tests

Add tests for:

* AI_GRADE=TRUE.
* AI_GRADE=FALSE.
* Case-insensitive configuration.
* Invalid environment values.
* Default configuration.
* Correct engine selection.
* Classic mode without machine-learning inference.
* AI mode with valid model availability.
* AI mode with missing models.
* Training scheduler behaviour in both modes.
* Cache invalidation when switching modes.
* Recommendation consistency.
* All three recommendation categories.
* Dashboard refresh functionality in both modes.

Make sure the application remains functional without loading any machine-learning model in classic mode.

## PART 2 — tutorial.md: Complete Installation and Deployment Guide

### 9. Objective

Create a clear, practical and self-contained file at the root of the repository:

```
tutorial.md
```

Its purpose is to allow someone to install, configure, build and deploy the entire application on a completely new Linux server.
The tutorial must be written for someone who can follow Linux and Docker commands but should not need to understand the application's internal architecture.
It must explain everything step by step.
Do not simply copy the existing architecture documentation.
This must be an actual installation and deployment tutorial.

### 10. Critical Docker Compose requirement

I specifically want ONE canonical, production-ready Docker Compose file:

```
docker-compose.yml
```

This file must contain the complete production application configuration.
I do not want to have to combine multiple Compose files manually to deploy the application.
Inspect the existing deployment architecture and consolidate the current configuration appropriately.
The final canonical `docker-compose.yml` should include all required services:

* Frontend.
* Backend.
* PostgreSQL.
* Redis.
* Background workers.
* Scheduler.
* Recommendation and machine-learning components, where separate containers are actually necessary.
* Any other required application services.

Do not introduce unnecessary containers.

#### Docker Compose requirements

The single production Compose file must include:

* Correct build contexts.
* Dockerfiles.
* Persistent database storage.
* Required application volumes.
* Internal networks.
* External reverse-proxy network integration.
* Health checks.
* Restart policies.
* Appropriate CPU and memory limits.
* Environment-variable configuration.
* Service dependencies and health conditions.
* Secure internal networking.
* Appropriate service users.
* Logging configuration.
* Database migration execution strategy.

PostgreSQL and Redis must not be directly exposed to the public internet.
Do not publish unnecessary application ports.
The application must integrate with an already existing external Traefik deployment.

#### Traefik configuration

I use Traefik as my reverse proxy.
Provide clearly identified locations within `docker-compose.yml` where I can manually insert or configure my:

* Traefik labels.
* Domain name.
* Router rules.
* Certificate resolver.
* External Docker network name.

Use comments explaining exactly what needs to be modified.
Do not invent my actual Traefik configuration.
Make it obvious which values I need to supply.
The final Compose file should be deploy-ready once these few environment-specific details have been configured.

#### Environment variables

Provide a corresponding:

```
.env.example
```

It must list every required variable.
Include clear descriptions of:

* Domain.
* Steam API key.
* Secret keys.
* Database credentials.
* Redis configuration.
* AI_GRADE.
* Optional IGDB credentials.
* External provider settings.
* Any other required configuration.

No secrets may be hardcoded in `docker-compose.yml` or committed to Git.
Make sure `.env` is in `.gitignore`.
The application must validate its configuration before deployment.

### 11. tutorial.md content

The tutorial should have the following sections.

**Section A — Prerequisites.** Explain: recommended Linux operating system; required CPU, RAM and disk space; installing Docker Engine; installing the Docker Compose plugin; creating a dedicated application directory; necessary Linux permissions.

**Section B — Obtain the application.** Explain how to: clone the Git repository; enter the project directory; inspect the repository structure; identify the configuration files. Use actual repository paths and commands.

**Section C — Configure the application.** Explain how to: copy `.env.example` to `.env`; generate secure application secrets; configure database credentials; configure Redis; obtain and configure a Steam Web API key; configure optional IGDB credentials; set `AI_GRADE`; configure the application's domain. Explain which configuration values are mandatory and which are optional. Never include real credentials in the tutorial.

**Section D — Configure Traefik.** Explain: how the external Docker network must be configured; where to insert Traefik labels; which domain/router values need to be changed; how HTTPS certificate resolution works; how to verify routing and TLS. The tutorial must not assume that Traefik is installed by this application. It is an existing external service.

**Section E — Build and deploy.** Provide actual commands to: 1. validate the environment file; 2. validate Docker Compose configuration; 3. build images; 4. start services; 5. run database migrations; 6. verify container health; 7. inspect application logs; 8. confirm frontend availability. Prefer a simple sequence of commands that can be copied directly. Use the actual service names and actual Compose configuration. Do not invent placeholder service names in the final tutorial.

**Section F — First application setup.** Explain: opening the website; connecting a Steam account; Steam OpenID authentication; making Steam game details public; importing the library; waiting for initial game metadata processing; generating the first gamer profile; generating recommendations.

**Section G — Updating the application.** Explain how to: pull new Git changes; rebuild modified images; apply database migrations safely; restart services; check for errors; roll back where appropriate.

**Section H — Backup and restore.** Document the actual implemented backup and restore scripts. Explain: creating a backup; where backups are stored; how to restore; how to test a restore; what happens to existing data; how to restore safely on a different server. Do not invent commands: inspect the actual scripts and use their real interfaces.

**Section I — Troubleshooting.** Cover common problems: Docker Compose cannot start; database connection failure; Redis unavailable; invalid Steam API key; Steam authentication failure; private Steam game details; Traefik routing errors; HTTPS certificate problems; missing environment variables; failed database migrations; AI model unavailable; recommendation generation failures. Explain which logs to inspect.

**Section J — Maintenance.** Explain: checking service health; monitoring resource usage; updating images; checking disk usage; backing up regularly; rotating secrets when appropriate; checking database health.

### 12. Tutorial quality requirements

The tutorial must be:

* Written in straightforward English.
* Organised into numbered steps.
* Practical and concise.
* Technically accurate.
* Based on the actual repository.
* Suitable for a new Linux server.
* Copy/paste friendly.

Use fenced code blocks for commands.
Clearly distinguish:

* Commands to execute.
* Configuration values to edit.
* Optional steps.
* Mandatory steps.

Use warnings for destructive operations.
Do not assume the reader knows Docker Compose internals.
Every command must correspond to an actual file, service, script or configuration in the repository.
If an operation requires manual intervention, explain exactly what to do.
If something cannot be automated, state it explicitly.
The tutorial must not claim that the application is deploy-ready until the relevant commands and procedures have been validated.

### 13. Deployment validation

After creating or consolidating the Compose file:

* Validate it with Docker Compose.
* Verify that every required service is present.
* Verify that dependencies are correctly configured.
* Verify that persistent volumes work.
* Verify that database migrations execute correctly.
* Verify that health checks function.
* Verify that PostgreSQL and Redis remain internal.
* Verify that the external Traefik network integration is configurable.
* Verify that no secrets are committed.
* Verify that the deployment survives container restarts.

Where practical, test the deployment using a fresh set of Docker volumes in an isolated environment.
Do not delete existing production volumes.

### 14. Documentation maintenance

Update any existing deployment documentation to avoid conflicting instructions.
The `tutorial.md` file must become the primary step-by-step installation and deployment reference.
The README should link to it.
The architecture and deployment documentation should describe the underlying design, while tutorial.md should explain how to actually install and operate the application.
Avoid maintaining competing production Compose instructions.

### 15. Final report

At completion, provide:

**AI_GRADE**: where the environment variable is defined; how mode selection works; which modules are disabled in classic mode; how model training is affected; how to switch modes safely; tests and results.

**Docker Compose**: location of the canonical docker-compose.yml; services included; required manual configuration; external Traefik integration; configuration variables.

**Tutorial**: location of tutorial.md; sections implemented; commands validated; any deployment requirements that remain manual.

**Testing**: backend test results; frontend test results; Docker Compose validation; deployment tests; mode-switching tests; documentation validation.

Preserve all previously implemented application functionality.
Do not commit automatically.
Do not claim a feature is operational unless it has been tested.
