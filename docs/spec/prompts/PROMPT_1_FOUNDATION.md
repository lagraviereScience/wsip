# PROMPT 1 — Foundation, architecture and infrastructure

You are starting development of What Do You Want to Play?

Your first task is to inspect the existing repository and environment.

Do not assume the repository is empty.

Identify:
- Existing files.
- Existing application code.
- Existing Docker configuration.
- Available database infrastructure.
- Existing deployment conventions.

Do not overwrite unrelated projects or infrastructure.

## Objectives

1. Establish the project structure.
2. Implement the initial frontend.
3. Implement the backend foundation.
4. Configure PostgreSQL.
5. Configure Redis.
6. Configure Docker Compose.
7. Implement health endpoints.
8. Establish database migrations.
9. Establish automated tests.
10. Document the architecture.

## Required implementation

Build:

- Next.js frontend.
- FastAPI backend.
- PostgreSQL database.
- Redis.
- Docker Compose.
- Backend health endpoint.
- Frontend health check.
- Environment variable configuration.
- Basic application logging.
- Database migration infrastructure.

Create a professional, responsive application interface.

Use a coherent visual identity for What Do You Want to Play?

The frontend should be clean, modern and focused on game discovery.

Use placeholder game data only for visual development. Clearly separate mock data from real application data.

Do not yet implement the recommendation algorithms.

## Required documentation

Create:

- README.md.
- ARCHITECTURE.md.
- DATABASE.md.
- DEPLOYMENT.md.
- `.env.example`.
- ADR documents for significant architectural decisions.

## Acceptance criteria

- Application starts through Docker Compose.
- Frontend is accessible.
- Backend is accessible.
- PostgreSQL is persistent.
- Redis is operational.
- Migrations work.
- Health checks pass.
- Automated smoke tests pass.
- No secrets are committed.

Do not proceed until this foundation works.
