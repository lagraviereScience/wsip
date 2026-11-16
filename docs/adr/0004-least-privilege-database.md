# ADR-0004: Least-privilege database roles and internal network

- Status: Accepted · Date: 2026-11-14

## Context
Spec §35 requires least-privilege database access and that PostgreSQL, Redis and internal interfaces are never exposed.

## Decision
- Three PostgreSQL roles: superuser (container and backups only), schema owner (Alembic only) and runtime (DML only, via default privileges). They are created by a first-start init script. See DATABASE.md.
- PostgreSQL and Redis attach only to a Compose network with `internal: true`: no published ports and no outbound route. The backend joins both `internal` and `edge`.
- Redis requires a password and uses `maxmemory-policy noeviction` because it will also be the Celery broker.
- Each container receives only the secrets it needs (the backend never sees the owner or superuser passwords).

## Consequences
- A SQL-injection bug in the API cannot alter the schema.
- Role setup runs only on an empty volume. Changing passwords later is a manual `ALTER ROLE`.
- A restore must re-apply runtime grants (procedure in DEPLOYMENT.md).
- The runtime role can technically modify `alembic_version`. This is accepted for now, and a later migration may revoke it explicitly.
