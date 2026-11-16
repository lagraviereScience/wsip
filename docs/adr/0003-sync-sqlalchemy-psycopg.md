# ADR-0003: Synchronous SQLAlchemy 2 with psycopg 3

- Status: Accepted · Date: 2026-11-14

## Context
FastAPI supports async, but Celery tasks, Alembic and ML pipelines (pandas, NumPy, LightGBM) are synchronous. Keeping two data-access stacks (async for the API, sync for workers) doubles repository code.

## Decision
Use synchronous SQLAlchemy 2 sessions with the psycopg 3 driver everywhere. API endpoints that touch the database are plain `def` functions, which FastAPI runs in its threadpool. Sessions are created per request (`get_db` dependency). Connections use `pool_pre_ping`, a 15 s statement timeout and the UTC time zone.

## Consequences
- One repository layer serves both the API and workers.
- Concurrency per uvicorn worker is bounded by the threadpool (40 by default) and the connection pool (5 + 5 overflow). With 2 workers that comfortably covers the 100 concurrent user target, because recommendations are precomputed. Revisit with profiling. psycopg 3 also supports async if a hot path needs it.
