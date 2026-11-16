# ADR-0022: Prebuilt fixed-tag images (build.sh) and an image-only Compose file

- Status: Accepted · Date: 2026-11-16 · Owner request · Amends ADR-0021

## Context
After ADR-0021, deployment used one Compose file, but that file still contained:

- `build:` sections;
- a version variable (`APP_VERSION`);
- bind mounts of the PostgreSQL init scripts from the source tree.

The documented procedure also had extra steps: `init-env.sh`, `check-env.sh`,
`docker compose build`, `check-config` and `up --wait`. The workstation `.env` set
`COMPOSE_FILE`, so plain `docker compose` silently loaded an overlay.

The owner wants conventional Docker. After configuring one `.env`, deployment and
every update must be exactly `./build.sh` then `docker compose up -d`. Existing data
must always be preserved, and the live volume identity must not change.

## Decision
1. **`build.sh`** builds three images with plain `docker build`, always with the
   fixed tag `1.0`:
   - `wdywtp-backend:1.0` (`./backend`, target `runtime`);
   - `wdywtp-frontend:1.0` (`./frontend`);
   - `wdywtp-postgres:1.0` (`./docker/postgres`).

   There is no version management. The script checks Docker and the build contexts,
   stops on the first failure, and never starts containers or reads `.env`. It uses
   `--pull` (fresh base images) and `--provenance=false`, so an unchanged image
   keeps its ID.
2. **`docker/postgres/Dockerfile`** is `FROM postgres:18.7-trixie` plus the existing
   `provision.sh` and `initdb/01-roles.sh`. The official entrypoint and lifecycle are
   unchanged: it initialises only an empty volume, and otherwise logs "Skipping
   initialization". There is no custom lifecycle logic.
3. **`docker-compose.yml` references images only:** no `build:` and no bind mounts.
   - Local images use `pull_policy: never`, so a missing image fails at once with
     `No such image`.
   - Redis keeps the official pinned image with `pull_policy: missing`.
   - `APP_VERSION` is removed; the application's version default is `1.0`.
4. **Volume identity is kept.** The project name is still fixed by `name: wdywtp`,
   and the volume keys are unchanged (`postgres-data`, `redis-data`, `models`), so
   the live volumes are reused: `wdywtp_postgres-data`, created 2026-11-14, mounted at
   `/var/lib/postgresql`. They are normal Compose volumes, not `external`, so a new
   server creates them on the first `up`.
5. **Automatic checks:**
   - Compose `${VAR:?}` catches empty required values; `.env.example` now leaves the
     secrets empty instead of `change-me`, so a forgotten secret stops `up` before
     PostgreSQL initialises.
   - `migrate` runs `app.cli check-config --quiet`, then `alembic upgrade head` and
     the taxonomy sync.
   - Startup order uses `depends_on` conditions.
   - `init-env.sh` and `check-env.sh` remain optional helpers, never deployment
     steps.
6. **The workstation overlay moves to `docker/dev/compose.dev.yaml`.** It is a test
   tool, always named with `-f`, holds the integration-test services, and its
   test-database setup uses the `wdywtp-postgres` image. `COMPOSE_FILE` was removed
   from the workstation `.env`.

## Consequences
- A server needs `build.sh`'s images, `docker-compose.yml` and `.env`. The same two
  commands install and update it.
- There is no image history: rolling back means checking out the previous commit and
  running `./build.sh` again. A schema rollback still needs the pre-update backup
  (tutorial.md).
- Workstations without Traefik need the overlay (`-f docker/dev/compose.dev.yaml`)
  for localhost access. Plain `docker compose up -d` there runs the production
  configuration, which publishes no ports.
- Verified on 2026-11-16:
  - fresh-volume first install through a local Traefik;
  - existing data: rebuilt images plus a pending migration applied, with every row
    and the volume identical;
  - `restart`, and `down` then `up` without `-v`;
  - recreation of only the changed containers;
  - a missing-image failure;
  - build failure handling;
  - switching the real workstation project onto the new images: same volume,
    "Skipping initialization", all row counts identical.
