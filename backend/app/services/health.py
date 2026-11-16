"""Dependency health checks used by the readiness endpoint.

Failures are logged with full detail but reported to callers only as a status,
so the public endpoint never leaks hostnames, versions or error messages.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.database.redis import get_redis
from app.database.session import get_engine

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class CheckStatus(StrEnum):
    OK = "ok"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: CheckStatus
    latency_ms: float


def _timed(name: str, check: Callable[[], None]) -> CheckResult:
    start = time.perf_counter()
    try:
        check()
        status = CheckStatus.OK
    except Exception:
        logger.exception("health check failed", extra={"check": name})
        status = CheckStatus.FAIL
    return CheckResult(status=status, latency_ms=round((time.perf_counter() - start) * 1000, 2))


def _check_database(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar_one()


def _check_redis() -> None:
    if not get_redis().ping():
        raise RuntimeError("Redis PING returned a falsy response")


def expected_migration_heads() -> set[str]:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return set(script.get_heads())


def _check_migrations(engine: Engine) -> None:
    """Fail when the schema is behind (or ahead of) the code's migration heads."""
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    expected = expected_migration_heads()
    if current != expected:
        raise RuntimeError(f"schema at {sorted(current)}, code expects {sorted(expected)}")


def run_readiness_checks() -> dict[str, CheckResult]:
    engine = get_engine()
    results = {
        "database": _timed("database", lambda: _check_database(engine)),
        "redis": _timed("redis", _check_redis),
    }
    if results["database"].status is CheckStatus.OK:
        results["migrations"] = _timed("migrations", lambda: _check_migrations(engine))
    else:
        results["migrations"] = CheckResult(status=CheckStatus.FAIL, latency_ms=0.0)
    return results
