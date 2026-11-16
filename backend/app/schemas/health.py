from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ComponentHealth(BaseModel):
    status: Literal["ok", "fail"]
    latency_ms: float


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, ComponentHealth]
    # Active recommendation scoring mode (AI_GRADE): "ai" or "classic".
    scoring_mode: Literal["ai", "classic"]
