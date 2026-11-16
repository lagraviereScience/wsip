"""Data retention (docs/PRIVACY.md "Retention"): bounded growth, configurable.

- Recommendation runs that were **never shown** (no impression, click or other event
  refers to them) after ``unshown_run_retention_hours``: feedback triggers rebuilds,
  and most rebuilt lists are replaced before anyone sees them (Stage 6 load test:
  8,000 runs for 100 players in an hour).
- Shown recommendation runs older than ``recommendation_run_retention_days``.
- In both cases the latest run per player and category (what the pages show) is kept.
- Behaviour events older than ``event_retention_days``. Ratings, feedback state,
  preferences and model training inputs live in their own tables and are kept.
- Monitoring reports older than ``monitoring_retention_days``.
- Expired or revoked sessions are cleaned by ``cleanup_sessions`` separately.

A value of 0 keeps that data indefinitely.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session

from app.core.config import Settings


def _exec(session: Session, stmt: Any, params: dict[str, Any]) -> CursorResult[Any]:
    return cast(CursorResult[Any], session.execute(stmt, params))


def prune(session: Session, settings: Settings, now: datetime) -> dict[str, int]:
    out: dict[str, int] = {}
    if settings.unshown_run_retention_hours:
        out["unshown_recommendation_runs"] = _exec(
            session,
            text(
                """
                DELETE FROM recommendation_runs r
                 WHERE r.created_at < :cutoff
                   AND NOT EXISTS (SELECT 1 FROM behaviour_events e
                                    WHERE e.recommendation_run_id = r.id)
                   AND r.id NOT IN (
                       SELECT DISTINCT ON (user_id, category) id FROM recommendation_runs
                        ORDER BY user_id, category, created_at DESC, id DESC)
                """
            ),
            {"cutoff": now - timedelta(hours=settings.unshown_run_retention_hours)},
        ).rowcount
    if settings.recommendation_run_retention_days:
        out["recommendation_runs"] = _exec(
            session,
            text(
                """
                DELETE FROM recommendation_runs r
                 WHERE r.created_at < :cutoff
                   AND r.id NOT IN (
                       SELECT DISTINCT ON (user_id, category) id FROM recommendation_runs
                        ORDER BY user_id, category, created_at DESC, id DESC)
                """
            ),
            {"cutoff": now - timedelta(days=settings.recommendation_run_retention_days)},
        ).rowcount
    if settings.event_retention_days:
        out["behaviour_events"] = _exec(
            session,
            text("DELETE FROM behaviour_events WHERE occurred_at < :cutoff"),
            {"cutoff": now - timedelta(days=settings.event_retention_days)},
        ).rowcount
    if settings.monitoring_retention_days:
        out["model_monitoring_reports"] = _exec(
            session,
            text("DELETE FROM model_monitoring_reports WHERE day < :cutoff"),
            {"cutoff": (now - timedelta(days=settings.monitoring_retention_days)).date()},
        ).rowcount
    return out
