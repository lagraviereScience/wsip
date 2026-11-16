# ADR-0001: Modular monolith and repository layout

- Status: Accepted · Date: 2026-11-14

## Context
The spec (§6) requires a modular monolith, no Kubernetes/microservices, and modules that can be separated later. The target is 100 concurrent web users on a shared server.

## Decision
One repository with `frontend/` (Next.js) and `backend/` (FastAPI). The backend is a single Python package `app/` with the module tree from spec §6. The API, migrations and (later) Celery workers all run from **one backend image** with different commands. Tests live in `backend/tests/` (unit and integration), not inside `app/`, so they never ship in the runtime image.

## Consequences
- Code and schema versions cannot drift between API and workers.
- Module boundaries are enforced by convention and review (dependency rule in ARCHITECTURE.md), not by process isolation. If a module is later split out, its public surface is the service layer.
- Deviation from spec §6: `app/tests/` moved to `backend/tests/`.
