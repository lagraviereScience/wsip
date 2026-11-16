# Architecture Decision Records

Format: context → decision → consequences. Status is one of Proposed, Accepted,
Superseded. Supersede an ADR with a new one instead of editing its decision.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith and repository layout | Accepted |
| [0002](0002-same-origin-api-routing.md) | Same-origin API routing | Amended by 0023 (frontend forwards `/api/*`) |
| [0003](0003-sync-sqlalchemy-psycopg.md) | Synchronous SQLAlchemy 2 with psycopg 3 | Accepted |
| [0004](0004-least-privilege-database.md) | Least-privilege database roles and internal network | Accepted |
| [0005](0005-python-toolchain.md) | Python 3.12 and uv | Accepted |
| [0006](0006-frontend-stack.md) | Frontend stack and component library | Accepted |
| [0007](0007-mock-data-isolation.md) | Mock data isolation | Accepted |
| [0008](0008-steam-openid-verification.md) | Steam OpenID 2.0 verification without a third-party library | Accepted (implemented in Stage 2) |
| [0009](0009-collaborative-filtering-library.md) | `implicit` instead of LightFM for collaborative filtering | Accepted (implemented in Stage 4; LightFM skipped) |
| [0010](0010-server-side-sessions.md) | Server-side sessions with opaque cookies | Accepted |
| [0011](0011-background-jobs.md) | Celery workers with job state in PostgreSQL | Accepted |
| [0012](0012-taxonomy-as-code.md) | Canonical taxonomy defined in code, versioned mappings, raw tags kept | Accepted |
| [0013](0013-steam-store-metadata-source.md) | Steam Store metadata through Valve's public store APIs | Accepted |
| [0014](0014-sign-in-only-mode.md) | Sign-in-only mode, with a manual library and explicit ratings | Amended by 0015 (fallback only) |
| [0015](0015-automatic-steam-import-primary.md) | Automatic Steam import is the primary library source | Accepted (product decision) |
| [0016](0016-content-based-engine.md) | Content-based recommendation baseline and its data sources | Accepted |
| [0017](0017-behaviour-events-and-feedback-state.md) | Append-only behaviour log, separate current feedback state | Accepted |
| [0018](0018-training-data-privacy-and-model-lifecycle.md) | Pseudonymous training, factor-only artifacts, gated deployment | Accepted |
| [0019](0019-satisfaction-model.md) | Point-in-time LightGBM satisfaction model, calibrated before display | Accepted |
| [0020](0020-deployment-wide-scoring-mode.md) | Deployment-wide scoring mode (AI_GRADE) selected in one engine module | Accepted |
| [0021](0021-single-production-compose-file.md) | One canonical production Compose file, with an optional workstation overlay | Amended by 0022 and 0023 |
| [0022](0022-prebuilt-images-and-build-script.md) | Prebuilt fixed-tag images (build.sh) and an image-only Compose file | Accepted |
| [0023](0023-frontend-only-traefik-routing.md) | Traefik routes to the frontend only; the frontend forwards `/api/*` | Accepted |
