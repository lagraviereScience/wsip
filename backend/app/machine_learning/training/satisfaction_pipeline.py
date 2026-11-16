"""Satisfaction-model stage of the daily pipeline (prompt 5 D).

Prepare → validate → features → train → evaluate → compare with production →
register → deploy only if every gate passes. Otherwise the deployed model (if any)
stays, and recommendations keep working with it or with the content baseline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.machine_learning.satisfaction import model as sat_model
from app.machine_learning.satisfaction import training as sat_training
from app.machine_learning.training.pipeline import (
    _finish,
    catalogue_item_features,
    deploy,
    deployed_version,
    mark_failed,
    prune,
)
from app.models.ml import EvaluationResult, ModelVersion, TrainingRun

logger = logging.getLogger(__name__)

KIND = "satisfaction"
ALGORITHM = "lgbm_binary_calibrated"
KEEP_VERSIONS = 5


def train_satisfaction(
    session_factory: Callable[[], Session],
    settings: Settings,
    now: datetime,
    *,
    trigger: str = "schedule",
) -> int:
    with session_factory() as session:
        run = TrainingRun(
            kind=KIND, status="running", trigger=trigger, started_at=datetime.now(UTC)
        )
        session.add(run)
        session.commit()
        try:
            status, decision = _train(session, run, settings, now)
        except Exception as exc:
            mark_failed(session, run.id, exc, now)
            raise
        _finish(session, run, status, decision, now)
        return run.id


def _train(
    session: Session, run: TrainingRun, settings: Settings, now: datetime
) -> tuple[str, str]:
    ds = sat_training.build_dataset(
        session, settings.engine_params, catalogue_item_features(session)
    )
    assert ds is not None
    run.dataset_stats = dict(ds.stats)
    run.report = {"dataset": dict(ds.stats)}
    labels = int(ds.stats["labels"])
    if labels < settings.sat_min_labels:
        deployed = deployed_version(session, KIND)
        keep = f" Keeping {deployed.version}." if deployed else " Ranking stays on Match."
        return "skipped", (
            f"Not enough satisfaction labels: {labels} (need {settings.sat_min_labels}) from "
            f"{ds.stats['eligible_users']} eligible players.{keep}"
        )
    result = sat_training.train_and_evaluate(ds)
    deployed = deployed_version(session, KIND)
    gate_list = sat_training.gates(
        result, ds, settings, deployed.metrics.get("test") if deployed else None
    )
    result.report["gates"] = [
        {"name": g.name, "passed": g.passed, "detail": g.detail} for g in gate_list
    ]
    run.report = {**run.report, **result.report}
    for name, metrics in result.report["models"].items():
        for metric, value in metrics.items():
            if isinstance(value, int | float) and value == value:  # skip NaN
                session.add(
                    EvaluationResult(
                        training_run_id=run.id,
                        algorithm=name,
                        split="test",
                        metric=metric,
                        value=float(value),
                        n_users=int(ds.stats.get("players_with_labels", 0)),
                    )
                )
    for name, values in result.report.get("ranking", {}).items():
        if values.get("ndcg@5") is not None:
            session.add(
                EvaluationResult(
                    training_run_id=run.id,
                    algorithm=name,
                    split="test_ranking",
                    metric="ndcg@5",
                    value=float(values["ndcg@5"]),
                    n_users=int(values.get("players", 0)),
                )
            )
    session.flush()
    failed = [g for g in gate_list if not g.passed]
    if failed or result.model is None:
        keep = f" Keeping {deployed.version}." if deployed else " Ranking stays on Match."
        return "succeeded", "Not deployed: " + "; ".join(
            f"{g.name} ({g.detail})" for g in failed
        ) + "." + keep

    version = f"sat-{now:%Y%m%d-%H%M%S}-lgbm"
    categories = sat_training.enabled_categories(result.report)
    result.model.params["categories"] = categories
    path, sha = sat_model.save(settings.models_dir, version, result.model)
    new = ModelVersion(
        kind=KIND,
        version=version,
        algorithm=ALGORITHM,
        status="candidate",
        training_run_id=run.id,
        params={**result.model.params, "calibration": result.model.calibrator.method},
        dataset_stats=dict(ds.stats),
        metrics={
            "test": result.primary,
            "splits": result.report["splits"],
            "ranking": result.report["ranking"],
        },
        artifact_path=path,
        artifact_sha256=sha,
        feature_schema_version=ds.schema.version,
    )
    session.add(new)
    session.flush()
    lg = result.primary
    decision = (
        f"Deployed {version}: AUC {lg['auc']}, log loss {lg['logloss']}, ECE {lg['ece']} "
        f"(content baseline AUC {result.report['models']['content_logistic']['auc']}). "
        "Used for: " + ", ".join(c for c, on in categories.items() if on) + "."
    )
    deploy(session, new, reason=decision, now=now)
    prune(session, KIND, KEEP_VERSIONS, now)
    session.execute(
        update(EvaluationResult)
        .where(
            EvaluationResult.training_run_id == run.id,
            EvaluationResult.algorithm == "lgbm_calibrated",
        )
        .values(model_version_id=new.id)
    )
    return "succeeded", decision
