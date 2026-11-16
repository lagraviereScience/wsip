# ADR-0021: One canonical production Compose file, with an optional workstation overlay

- Status: Accepted, amended by [ADR-0022](0022-prebuilt-images-and-build-script.md) (build.sh, image-only Compose file, overlay moved to `docker/dev/`) · Date: 2026-11-15 · After Stage 6 (owner request)

## Context
Until Stage 6, production required combining three files:

- `compose.yaml`: base, with localhost ports and test services;
- `compose.traefik.yaml`: Traefik labels, which also removed the ports;
- `compose.prod.yaml`: production mode and limits.

There was also a separate `.env.production.example`, which `.gitignore` excluded by
mistake.

The owner wants a single, deploy-ready `docker-compose.yml` for a new server behind
an existing external Traefik, plus one `.env.example` and a step-by-step tutorial.
Docker Compose picks `compose.yaml` over `docker-compose.yml` when both exist, so the
two names cannot coexist.

## Decision
1. **`docker-compose.yml` is the production definition.** It contains:
   - all seven services (postgres, redis, migrate, backend, worker, scheduler,
     frontend) and the production limits;
   - restart policies, health checks and log rotation;
   - non-root, read-only containers;
   - an `internal`-only network for PostgreSQL and Redis;
   - an `edge` network for outbound calls;
   - the external Traefik network `proxy` (name from `TRAEFIK_NETWORK`);
   - Traefik labels in clearly marked "edit here" blocks, driven by `.env`;
   - no published ports, and no secrets.

   Required values use `${VAR:?message}`. `APP_ENV` defaults to `production`.
2. **Migrations:** `migrate` is a one-shot service on every `up`. `backend`, `worker`
   and `scheduler` depend on its successful completion, so neither an invalid
   configuration nor a failed migration starts the new code. The scheduler gets
   runtime DB credentials only because shared settings validation requires them in
   production. Without them it could not start; the deployment test found this.
3. **`compose.dev.yaml` is an optional workstation overlay.** It is enabled only via
   `COMPOSE_FILE=docker-compose.yml:compose.dev.yaml` in a workstation `.env`, and
   provides:
   - development mode;
   - `127.0.0.1` ports;
   - Traefik disabled, with `proxy: !override {}` giving each project a private
     network (so dev and perf stacks don't collide);
   - the integration-test services.

   A server never uses it.
4. **One `.env.example`** documents every variable, required versus optional, with
   workstation lines commented out at the end. `.env.production.example` is removed.
5. **Validation before deployment:**
   - `scripts/check-env.sh` parses `.env` without executing it and never prints
     secrets;
   - `python -m app.cli check-config` checks inside the image.
6. **Scripts work without published ports:**
   - `security-check.sh` reads headers inside the containers, and skips the
     dependency audits when `uv`/`npm` are absent;
   - `restore-db.sh` checks readiness inside the backend container.
7. **Documentation:**
   - [tutorial.md](../../tutorial.md) is the step-by-step reference;
   - [DEPLOYMENT.md](../../DEPLOYMENT.md) describes the design only.

## Consequences
- A server needs only `docker-compose.yml`, `.env` and the repository's build
  contexts. Plain `docker compose ...` commands work there without `-f` flags.
- Workstations need the extra `COMPOSE_FILE` line and placeholder Traefik values,
  because the base file requires them.
- Project and volume names (`wdywtp_*`) are unchanged, so existing data volumes carry
  over. The development stack was recreated on the new layout without data loss.
- Verified on 2026-11-15:
  - a fresh copy of the repository with fresh volumes, behind a throwaway Traefik
    v3.6: routing, HSTS, the security check, persistence, restarts, backup and both
    restore modes, a restore onto a second deployment with different secrets,
    password rotation, and a migration downgrade and upgrade.
  - Not verified: a real ACME certificate, and the real server.
