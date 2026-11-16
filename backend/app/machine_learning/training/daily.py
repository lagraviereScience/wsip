"""The daily training pipeline: collaborative models, then the satisfaction model.

Each stage is isolated: a failure is recorded (``training_runs.status = failed``)
and the next stage still runs. Deployed models are only replaced by a deploy that
passed its gates, so a failed or skipped run never interrupts recommendations.
Every run writes an evaluation report (JSON in ``training_runs.report``, Markdown
under ``<models_dir>/reports/``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.machine_learning import reports
from app.machine_learning.training.pipeline import train_collaborative
from app.machine_learning.training.satisfaction_pipeline import train_satisfaction
from app.models.ml import ModelVersion, TrainingRun

logger = logging.getLogger(__name__)

STAGES: dict[str, Callable[..., int]] = {
    "collaborative": train_collaborative,
    "satisfaction": train_satisfaction,
}


@dataclass
class DailyResult:
    runs: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    deployed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def _latest_run_id(session: Session, kind: str) -> int | None:
    run = (
        session.query(TrainingRun)
        .filter(TrainingRun.kind == kind)
        .order_by(TrainingRun.id.desc())
        .first()
    )
    return run.id if run else None


def run_daily_training(
    session_factory: Callable[[], Session],
    settings: Settings,
    now: datetime,
    *,
    trigger: str = "schedule",
    only: str | None = None,
) -> DailyResult:
    result = DailyResult()
    for kind, stage in STAGES.items():
        if only and only != kind:
            continue
        try:
            run_id = stage(session_factory, settings, now, trigger=trigger)
        except Exception as exc:
            result.errors[kind] = f"{type(exc).__name__}: {exc}"
            with session_factory() as session:
                rid = _latest_run_id(session, kind)
            if rid is None:
                continue
            run_id = rid
        result.runs[kind] = run_id
        with session_factory() as session:
            run = session.get_one(TrainingRun, run_id)
            result.statuses[kind] = run.status
            deployed = (
                session.query(ModelVersion)
                .filter_by(training_run_id=run_id, status="deployed")
                .one_or_none()
            )
            if deployed is not None:
                result.deployed.append(deployed.version)
            try:
                run.report_path = reports.write(settings.models_dir, run)
                session.commit()
            except OSError:
                logger.exception("could not write the evaluation report file")
    return result
