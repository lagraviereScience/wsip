# Deployment design

**To install, update or operate the site, follow [tutorial.md](tutorial.md).** This
document explains how the deployment is built and why; it holds no competing
step-by-step instructions.

Target: a Linux server with Docker Compose, behind an **existing** Traefik that
terminates HTTPS. This repository never creates Traefik or its network. The routing
values (host rule, entrypoint, certificate resolver and Traefik network name) are
written directly in `docker-compose.yml` for the current server, not read from `.env`
([ADR-0023](docs/adr/0023-frontend-only-traefik-routing.md)). Another server edits those
lines (section 3).

## 1. Files and workflow

Deployment and every update are the same two commands, after `.env` is configured
([ADR-0022](docs/adr/0022-prebuilt-images-and-build-script.md)):

```bash
./build.sh             # build the images (fixed tag 1.0)
docker compose up -d   # run them
```

| File | Role |
|---|---|
| `build.sh` | Builds the three local images with plain `docker build`, always tagged `1.0` (no versioning). Checks Docker, stops on the first failure, never starts containers, never reads `.env`. |
| `docker-compose.yml` | **The** deployment: every service, network, volume, limit, health check and Traefik label. Only `image:` references, **no `build:`**. Local images use `pull_policy: never` (a missing image fails with `No such image`), Redis uses `pull_policy: missing`. |
| `.env` | The only runtime configuration, next to `docker-compose.yml`, read automatically by Compose. Template: `.env.example`. |
| `docker/postgres/Dockerfile` | `postgres:18.7-trixie` + the provisioning scripts. |
| `docker/dev/compose.dev.yaml` | Workstation/test overlay (localhost ports, test services). **Not in this repository**: README, `perf/stack.sh` and the test docs refer to it, but the file was not committed. |
| `perf/compose.perf.yaml` | Isolated load-test overlay (docs/PERFORMANCE.md). It is layered on `docker/dev/compose.dev.yaml`, so it cannot run from this repository as is. |

| Image | Build context | Used by |
|---|---|---|
| `wdywtp-backend:1.0` | `./backend` (target `runtime`) | migrate, backend, worker, scheduler |
| `wdywtp-frontend:1.0` | `./frontend` | frontend |
| `wdywtp-postgres:1.0` | `./docker/postgres` | postgres |
| `redis:8.10.3-alpine` | official, pulled if missing | redis |

The images are self-contained. No source code is bind-mounted; at runtime a server
needs only the images, `docker-compose.yml` and `.env`. Builds use `--pull` (fresh
base images) and `--provenance=false`, so an unchanged image keeps its ID. On
`up -d`, Compose recreates exactly the containers whose image content or
configuration changed.

History: Stage 6 used three Compose files (`compose.yaml`, `compose.traefik.yaml`,
`compose.prod.yaml`, merged by ADR-0021), then `docker-compose.yml` still contained
`build:` sections and a version variable (`APP_VERSION`). Both were replaced by this
workflow.

## 2. Services and networks

```
 internet ──► Traefik (existing) ──► frontend :3000           external Traefik network
                                       │  /api/* (Next.js rewrite)  (private_secured_network)
                                       ▼
                                     backend :8000             network "edge" (alias wdywtp-backend)
 backend, worker ──► Steam / IGDB (outbound)                   network "edge"
 backend, worker, scheduler, migrate ──► postgres, redis       network "internal" (no route out;
                                                               aliases wdywtp-postgres, wdywtp-redis)
```

| Service | Image | Networks | Health check | Restart | CPU / memory |
|---|---|---|---|---|---|
| postgres | wdywtp-postgres:1.0 (postgres:18.7) | internal | `pg_isready` over TCP | unless-stopped | 2 / 2 GiB |
| redis | redis:8.10.3-alpine | internal | `PING` | unless-stopped | 1 / 768 MiB (`maxmemory` 512 MiB, `noeviction`, AOF) |
| migrate | wdywtp-backend:1.0 | internal | none (one-shot) | no | none |
| backend | wdywtp-backend:1.0 | internal, edge | `/api/health/live` (image) | unless-stopped | 2 / 1 GiB |
| worker | wdywtp-backend:1.0 | internal, edge | Celery ping | unless-stopped | 2 / 2 GiB |
| scheduler | wdywtp-backend:1.0 | internal | none (one instance) | unless-stopped | 0.5 / 256 MiB |
| frontend | wdywtp-frontend:1.0 | edge, Traefik network | `/healthz` (image) | unless-stopped | 1 / 768 MiB |

- **No published ports.** The only way in is Traefik, over the external Traefik
  network. Only `frontend` joins it; the backend is reached through the frontend's
  `/api/*` rewrite over `edge`. PostgreSQL and Redis are only on `internal`
  (`internal: true`, no route to the outside). `scripts/security-check.sh` verifies the
  port and network rules on the running stack.
- **Unique aliases.** The Traefik network is shared with other stacks on the server,
  where names like `postgres`, `redis` or `backend` can resolve to other containers.
  The app therefore connects to `wdywtp-postgres`, `wdywtp-redis` and `wdywtp-backend`.
- **Users and filesystems.** The application containers run as non-root (uid 10001
  and 1000) with read-only root filesystems, `no-new-privileges` and all capabilities
  dropped. Writable paths: `/tmp` (tmpfs), the frontend's `.next/cache` (tmpfs) and
  the `models` volume (worker).
- **Volumes.** `postgres-data` (all durable data), `redis-data` (queues, AOF) and
  `models` (trained model files). `docker compose down` keeps them; only `down -v`
  deletes them.
- **Logging.** Docker `json-file` with rotation (10 MB × 5 per container). The
  backend and worker write one JSON object per line with a `request_id`. Point the
  server's log collector (Loki/Promtail, Vector, Fluent Bit, ...) at the Docker logs;
  none is bundled.

## 3. Traefik integration

Only `frontend` has Traefik labels ([ADR-0023](docs/adr/0023-frontend-only-traefik-routing.md)).
They define one router, `wsip`, with literal values:

| Label | Sets |
|---|---|
| `traefik.http.routers.wsip.rule` | `Host(...)`: the site's domain |
| `traefik.http.routers.wsip.entrypoints` | `websecure` |
| `traefik.http.routers.wsip.tls.certresolver` | the certificate resolver name in the server's Traefik |
| `traefik.http.services.wsip.loadbalancer.server.port` | `3000` |

The external network is declared at the end of the file (`private_secured_network`,
`external: true`). To deploy elsewhere, edit the host rule, entrypoint, resolver and
network name in `docker-compose.yml`. The `.env` variables `PUBLIC_HOSTNAME`,
`TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT` and `TRAEFIK_CERT_RESOLVER` are not read by the
Compose file. `PUBLIC_BASE_URL` still matters: it must be `https://<the domain>`, as it
is the Steam OpenID return address and the CSRF origin.

`/api/*` reaches the backend through the Next.js rewrite in the frontend image. Its
target, `http://wdywtp-backend:8000`, is compiled in at build time (`BACKEND_INTERNAL_URL`
build argument in `frontend/Dockerfile`).

**HSTS** is not set by this application: there is no Traefik headers middleware and
neither app sends `Strict-Transport-Security`. Add it in the server's Traefik
configuration, or add a headers middleware label to `frontend`.

**`FORWARDED_ALLOW_IPS`** is required. uvicorn accepts `X-Forwarded-For` only from
these addresses, so rate limits see real client IPs and nobody else can spoof them.
The backend's direct peer is now the frontend container on `edge`, so the value must
include the `edge` network's subnet as well as Traefik's network address, for example
`172.18.0.0/16,172.19.0.0/16`. The `edge` subnet exists only after the first
`docker compose up -d`:

```bash
docker network inspect wdywtp_edge --format '{{(index .IPAM.Config 0).Subnet}}'
```

With only Traefik's subnet, every visitor shares the frontend's address for the per-IP
limits, including sign-in (20 per minute). Whether the Next.js rewrite forwards
`X-Forwarded-For` has not been verified on this layout.

The routing tests of 2026-11-15 (local Traefik v3.6: routes, HSTS, headers, default
certificate) used the earlier two-router layout, not this one.

## 4. Configuration and secrets

- All configuration except the Traefik routing (section 3) comes from `.env` (mode
  600, never committed, `.gitignore` covers `.env` and `.env.*` except
  `.env.example`). `docker-compose.yml` contains no secret; required values use
  `${VAR:?message}` so Compose refuses to start without them.
- Settings with a default in `app/core/config.py` but no line in `docker-compose.yml`
  (for example `SESSION_TTL_DAYS`, `DB_POOL_SIZE`, the retention periods other than
  `EVENT_RETENTION_DAYS`) cannot be changed from `.env` alone: Compose passes each
  container only the variables listed under its `environment`.
- Each service receives only what it needs. The superuser password goes only to
  postgres. The schema-owner role goes only to migrate. The scheduler gets the
  runtime database credentials only because the shared settings validation requires
  them in production; it never connects to the database.
- Validation is automatic, with no manual step:
  - `docker compose up -d` refuses to start while a required `.env` value is empty
    (`${VAR:?message}`);
  - `migrate` first runs `python -m app.cli check-config --quiet`. It prints the
    invalid settings and exits 1, so nothing else starts;
  - every service validates again at start: in production they refuse placeholder
    secrets, an http `PUBLIC_BASE_URL` or an invalid `AI_GRADE`.

  Validation errors never echo the environment. `scripts/check-env.sh` remains an
  optional plain-language diagnostic.
- Role passwords are stored in PostgreSQL when the volume is first initialised.
  Rotating them needs `ALTER ROLE` first (tutorial.md section I, rehearsed 2026-11-15).

## 5. Database lifecycle and migrations

PostgreSQL follows the official image's lifecycle unchanged:

- **Empty volume** (first installation): Compose creates the named volume, the
  entrypoint runs `initdb`, then `/docker-entrypoint-initdb.d/01-roles.sh` (from the
  image) creates the database, the owner role and the runtime role.
- **Existing volume**: the entrypoint logs "Skipping initialization" and reuses the
  data directory; the init scripts never run again.

Nothing in the deployment deletes, copies, resets or replaces data. The volume
identity is `<project>_postgres-data`. The project name is fixed to `wdywtp` by
`name:` in `docker-compose.yml`, so the volume is always `wdywtp_postgres-data`,
mounted at `/var/lib/postgresql` (PGDATA `/var/lib/postgresql/18/docker`). On the
existing installation this is the volume created on 2026-11-14, verified to be
reused by the new images. The volume is a normal Compose volume (not `external`),
so a new server creates it on the first `up`.

`migrate` is a one-shot container that runs on every `docker compose up`. It checks
the configuration, runs `alembic upgrade head` with the schema-owning role (pending
revisions only), syncs the taxonomy (idempotent), and exits. `backend`, `worker` and `scheduler` depend on it with
`service_completed_successfully`, so:

- the new code never runs against an old schema;
- a failed migration, or invalid configuration, keeps the new services from starting.

Each migration runs in its own transaction (`transaction_per_migration`).
`/api/health/ready` reports `503` while the schema and the code disagree.

## 6. Scoring mode (AI_GRADE)

`AI_GRADE` (default `TRUE`) is passed to every backend-image service. It selects the
recommendation engine for the whole deployment; changing it means
`docker compose up -d`, which recreates migrate, backend, worker and scheduler. See
[docs/SCORING_MODES.md](docs/SCORING_MODES.md).

## 7. Capacity

The limits above were load-tested with 100 concurrent signed-in players while daily
training, library syncs and a burst of recommendation rebuilds ran
([docs/PERFORMANCE.md](docs/PERFORMANCE.md)) on the earlier layout, where Traefik sent
`/api/*` straight to the backend. Database connections per API process: pool 10 +
overflow 10 (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW` settings; `docker-compose.yml` does not
pass them, so changing them needs an `environment` entry). Keep
`WEB_CONCURRENCY × 20 + worker` under the runtime role's limit of 60 connections. The
worker's 2 CPUs bound how fast recommendation rebuilds drain (about 370 per minute).
To scale the API, raise its `cpus` limit and `WEB_CONCURRENCY` together.

## 8. Health, restarts and operations

- Backend and frontend health checks test liveness only, so a database outage does
  not cause restart loops. `/api/health/ready` (database, Redis, schema version, and
  the active `scoring_mode`) is for monitoring.
- Restart behaviour was verified on 2026-11-15 on a test deployment. A killed API
  process is restarted by `unless-stopped`. `docker compose restart` and
  `down`/`up` keep all data (`scripts/verify-persistence.sh`).
- Administration happens through commands; there are no admin web endpoints (spec
  §35):

  ```bash
  docker compose exec worker python -m app.cli status    # mode, DB, queues, workers, providers, latency, disk
  docker compose exec worker python -m app.cli monitor   # model quality report and alerts
  docker compose exec worker python -m app.cli models | report | train | rollback <version>
  ```

## 9. Backups

`scripts/backup-db.sh` and `scripts/restore-db.sh`. See
[docs/BACKUP_AND_RECOVERY.md](docs/BACKUP_AND_RECOVERY.md) for the design and
tutorial.md section H for the commands. Model artifacts are optional to back up (the
next training run rebuilds them). Redis needs no backup.

## 10. Not yet in place

- Deployment on the real server, with its real domain and certificate (not verified).
- HSTS (section 3): not set by the application since the routing change.
- Client IP forwarding through the frontend (section 3): not verified.
- `scripts/check-env.sh` still requires `PUBLIC_HOSTNAME`, `TRAEFIK_NETWORK` and
  `TRAEFIK_CERT_RESOLVER`, and checks that `TRAEFIK_NETWORK` exists, although the Compose
  file no longer uses them.
- The workstation overlay `docker/dev/compose.dev.yaml`, the backend and frontend test
  suites, `scripts/smoke-test.sh` and `scripts/generate-api-docs.py` are referenced by the
  docs but not in this repository.
- Pushing alerts to an alerting system. They are stored and shown by `status` and
  `monitor`; wiring them up needs the server's monitoring stack (OPEN_QUESTIONS #14, #32).
- Dependency scanning in CI. Run `scripts/security-check.sh` on a workstation before
  each release.
- Shipping backups off the host (the operator chooses the target).
