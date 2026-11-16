"""Health endpoints.

- ``/live``  — process is up. No dependencies; used by the Docker health check so a
  database outage does not cause restart loops.
- ``/ready`` — process can serve traffic: PostgreSQL, Redis and schema version OK.
  Returns 503 otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.schemas.health import ComponentHealth, LivenessResponse, ReadinessResponse
from app.services.health import CheckStatus, run_readiness_checks

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    settings = get_settings()
    return LivenessResponse(service="backend", version=settings.app_version)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(response: Response) -> ReadinessResponse:
    """Database, Redis and schema version checks (503 if any fails), plus the active
    recommendation ``scoring_mode`` ("ai" or "classic", from AI_GRADE)."""
    results = run_readiness_checks()
    healthy = all(r.status is CheckStatus.OK for r in results.values())
    response.headers["Cache-Control"] = "no-store"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if healthy else "unavailable",
        scoring_mode=get_settings().scoring_mode,
        checks={
            name: ComponentHealth(status=r.status.value, latency_ms=r.latency_ms)
            for name, r in results.items()
        },
    )
