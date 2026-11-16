# ADR-0011: Celery workers with job state in PostgreSQL

- Status: Accepted · Date: 2026-11-14

## Context
Library imports and metadata ingestion call external APIs with rate limits and failure modes. They must not run inside web requests (spec §5, §7).

## Decision
- One Celery worker service (concurrency 2, `max-tasks-per-child=100`) consumes three queues: `imports` (user-triggered), `catalogue` (bulk metadata) and `default` (housekeeping). It runs from the same image as the API.
- One `scheduler` service (Celery beat) handles periodic jobs: due library re-syncs every hour, stale metadata every 6 hours, Steam vocabulary daily, and session cleanup daily.
- Redis logical DB 1 is the broker. No result backend is used. User-visible job state lives in `library_sync_runs`, and a partial unique index allows at most one queued or running import per user.
- Tasks are thin wrappers over services, which are tested without Celery.
- Outbound calls to each provider are paced by a Redis-backed `OutboundThrottle` shared by all processes. The Steam Web API defaults to 60 calls/min, well under 100,000/day, and the Steam Store to 30 calls/min.
- Celery logging goes through the application's JSON logging (`setup_logging` signal).

## Consequences
- Re-running a task is safe. Imports start from a run row in `queued` state, and catalogue writes are upserts.
- If Redis loses queued messages, affected runs stay `queued`. A later stage should add a reaper that requeues stale `queued` runs.
