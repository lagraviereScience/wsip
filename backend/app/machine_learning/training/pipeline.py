"""Daily collaborative training pipeline (spec §24).

1. Collect eligible events (opted-in, active users only) into a pseudonymised dataset.
2. Validate: enough players and positive interactions, and new data since the
   deployed model. Otherwise the run is ``skipped`` and the deployed model stays.
3. Generate features: game metadata rolled up over the taxonomy (hybrid models).
4. Train every candidate algorithm and both baselines on a chronological split.
5. Evaluate (warm and cold-item splits) and store every metric.
6. Compare: the best collaborative model must beat popularity by a margin, not
   increase explicit negatives, and not be clearly worse than the deployed model.
7. Deploy only if all gates pass: retrain on all data, write the artifact, mark it
   deployed, retire the previous version (kept for rollback).

Daily execution is not daily deployment: most days are expected to be "kept".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.machine_learning.benchmark import index_for, run_split
from app.machine_learning.datasets.interactions import (
    InteractionDataset,
    build_training_dataset,
)
from app.machine_learning.evaluation import chronological_split, cold_item_split, pair_values
from app.machine_learning.models.factorization import BASELINES, CF_ALGORITHMS, make_model
from app.machine_learning.registry import store
from app.models.ml import (
    AccountDeletion,
    EvaluationResult,
    ModelDeploymentHistory,
    ModelVersion,
    TrainingRun,
)
from app.recommendations.features.vectors import category_shares, rollup_shares
from app.repositories import recommendation as rec_repo

logger = logging.getLogger(__name__)

KIND = "collaborative"
CF_SCHEMA_VERSION = "cf-signals-v1"  # signal channels and weights (datasets/interactions.py)
PRIMARY = "ndcg@5"
MIN_NEW_DATA = 0.02  # retrain only with >= 2% more positive pairs than the deployed model
DEPLOYED_TOLERANCE = 0.9  # a new model may not score below 90% of the deployed one
RETIRED_ARTIFACT_MAX_AGE = timedelta(days=30)


def catalogue_item_features(session: Session) -> dict[int, dict[int, float]]:
    """Rolled-up feature shares x metadata confidence for every catalogue game."""
    taxonomy = rec_repo.load_taxonomy(session)
    out: dict[int, dict[int, float]] = {}
    for gid, vec in rec_repo.load_game_vectors(session).items():
        if vec.is_empty:
            continue
        conf = sum(f.confidence for f in vec.features.values()) / len(vec.features)
        rolled = rollup_shares(category_shares(vec, taxonomy), taxonomy)
        out[gid] = {fid: round(share * conf, 4) for fid, share in rolled.items() if share > 0}
    return out


def deployed_version(session: Session, kind: str = KIND) -> ModelVersion | None:
    return session.execute(
        select(ModelVersion).where(ModelVersion.kind == kind, ModelVersion.status == "deployed")
    ).scalar_one_or_none()


def _gates(
    warm: Mapping[str, Mapping[str, Any]],
    settings: Settings,
    deployed: ModelVersion | None,
    test_users: int,
) -> tuple[str | None, str]:
    """(winning algorithm or None, decision text)."""
    if test_users < settings.cf_min_test_users:
        return None, f"Only {test_users} test users (need {settings.cf_min_test_users})."
    pop = warm.get("popularity", {})
    pop_score = float(pop.get(PRIMARY, 0.0))
    ranked = sorted(
        (a for a in CF_ALGORITHMS if warm.get(a, {}).get("users")),
        key=lambda a: (-float(warm[a][PRIMARY]), a),
    )
    if not ranked:
        return None, "No collaborative model produced evaluable results."
    best = ranked[0]
    score = float(warm[best][PRIMARY])
    if score < pop_score * settings.cf_min_lift_over_popularity or score <= 0:
        return None, (
            f"Best model {best} ({PRIMARY} {score:.4f}) does not beat popularity "
            f"({pop_score:.4f}) by {settings.cf_min_lift_over_popularity:.2f}x."
        )
    neg = float(warm[best].get("negative_rate@5", 0.0))
    if neg > float(pop.get("negative_rate@5", 0.0)) + 0.02:
        return None, f"{best} recommends more explicitly rejected games than popularity."
    if deployed is not None:
        old = float(deployed.metrics.get("warm", {}).get(PRIMARY, 0.0))
        if score < old * DEPLOYED_TOLERANCE:
            return None, (
                f"{best} ({PRIMARY} {score:.4f}) is clearly worse than the deployed "
                f"{deployed.version} ({old:.4f}); keeping the deployed model."
            )
    return best, f"Deployed {best}: {PRIMARY} {score:.4f} vs popularity {pop_score:.4f}."


def _finish(session: Session, run: TrainingRun, status: str, decision: str, now: datetime) -> None:
    run.status, run.decision, run.finished_at = status, decision, datetime.now(UTC)
    run.report = {**(run.report or {}), "kind": run.kind, "status": status, "decision": decision}
    session.commit()
    logger.info(f"{run.kind} training finished", extra={"status": status, "decision": decision})


def train_collaborative(
    session_factory: Callable[[], Session],
    settings: Settings,
    now: datetime,
    *,
    trigger: str = "schedule",
) -> int:
    """Run the pipeline once. Returns the training run id."""
    with session_factory() as session:
        run = TrainingRun(
            kind=KIND, status="running", trigger=trigger, started_at=datetime.now(UTC)
        )
        session.add(run)
        session.commit()
        try:
            features = catalogue_item_features(session)
            dataset = build_training_dataset(session, features)
            run.dataset_stats = dict(dataset.stats)
            decision = _train(session, run, dataset, settings, now)
        except Exception as exc:
            mark_failed(session, run.id, exc, now)
            raise
        _finish(session, run, decision[0], decision[1], now)
        return run.id


def mark_failed(session: Session, run_id: int, exc: BaseException, now: datetime) -> None:
    """Record a failed run. Deployed models are untouched, so serving continues."""
    session.rollback()
    run = session.get_one(TrainingRun, run_id)
    run.status, run.error, run.finished_at = (
        "failed",
        f"{type(exc).__name__}: {exc}"[:500],
        datetime.now(UTC),
    )
    run.report = {"kind": run.kind, "status": "failed", "error": run.error}
    session.commit()
    logger.exception(f"{run.kind} training failed")


def _train(
    session: Session,
    run: TrainingRun,
    dataset: InteractionDataset,
    settings: Settings,
    now: datetime,
) -> tuple[str, str]:
    stats = dataset.stats
    users, positives = int(stats["users_with_signals"]), int(stats["positive_pairs"])
    if users < settings.cf_min_users or positives < settings.cf_min_positive_pairs:
        return "skipped", (
            f"Not enough data for collaborative filtering: {users} players with signals "
            f"(need {settings.cf_min_users}) and {positives} positive interactions "
            f"(need {settings.cf_min_positive_pairs}). Content-based recommendations only."
        )
    deployed = deployed_version(session)
    if deployed is not None and run.trigger == "schedule":
        before = int(deployed.dataset_stats.get("positive_pairs", 0))
        deletions = session.execute(
            select(func.count())
            .select_from(AccountDeletion)
            .where(AccountDeletion.deleted_at > deployed.created_at)
        ).scalar_one()
        if not deletions and positives < before * (1.0 + MIN_NEW_DATA):
            return "skipped", (
                f"Little new data since {deployed.version} ({positives} vs {before} positive "
                "interactions); keeping it."
            )

    results: dict[str, dict[str, dict[str, Any]]] = {}
    test_users = 0
    for split in (chronological_split(dataset.signals), cold_item_split(dataset.signals)):
        if split.name == "warm":
            test_users = split.n_test_users
        results[split.name] = run_split(split, dataset, BASELINES + CF_ALGORITHMS)
        run.report = {
            **(run.report or {}),
            "dataset": dict(stats),
            "results": {**(run.report or {}).get("results", {}), split.name: results[split.name]},
        }
        for algo, metrics in results[split.name].items():
            for metric, value in metrics.items():
                if metric in ("users", "fit_seconds"):
                    continue
                session.add(
                    EvaluationResult(
                        training_run_id=run.id,
                        algorithm=algo,
                        split=split.name,
                        metric=metric,
                        value=float(value),
                        n_users=int(metrics.get("users", 0)),
                    )
                )
    session.flush()

    best, decision = _gates(results["warm"], settings, deployed, test_users)
    if best is None:
        return "succeeded", decision

    # Retrain the winner on all data and deploy it.
    index = index_for(dataset)
    model = make_model(best)
    model.fit(
        index.matrix(pair_values(dataset.signals)), index.feature_matrix(dataset.item_features)
    )
    version = f"cf-{now:%Y%m%d-%H%M%S}-{best}"
    path, sha = store.save(settings.models_dir, version, model, index.items)
    new = ModelVersion(
        kind=KIND,
        version=version,
        algorithm=best,
        status="candidate",
        training_run_id=run.id,
        params=model.params(),
        dataset_stats=dict(stats),
        metrics={split: res[best] for split, res in results.items()},
        artifact_path=path,
        artifact_sha256=sha,
        feature_schema_version=CF_SCHEMA_VERSION,
    )
    session.add(new)
    session.flush()
    deploy(session, new, reason=decision, now=now)
    prune(session, KIND, settings.cf_keep_versions, now)
    session.execute(
        update(EvaluationResult)
        .where(EvaluationResult.training_run_id == run.id, EvaluationResult.algorithm == best)
        .values(model_version_id=new.id)
    )
    return "succeeded", decision


def deploy(
    session: Session, version: ModelVersion, *, reason: str, now: datetime, action: str = "deploy"
) -> None:
    """Make ``version`` the deployed model; the previous one is retired (kept)."""
    previous = deployed_version(session, version.kind)
    if previous is not None and previous.id != version.id:
        previous.status, previous.retired_at = "retired", now
        session.flush()
    version.status, version.deployed_at, version.retired_at = "deployed", now, None
    session.add(
        ModelDeploymentHistory(
            model_version_id=version.id,
            previous_model_version_id=previous.id if previous else None,
            action=action,
            reason=reason,
        )
    )
    session.flush()


def rollback(session: Session, version: str, now: datetime) -> ModelVersion:
    """Redeploy an earlier version (of its kind) whose artifact is still kept."""
    target = session.execute(
        select(ModelVersion).where(ModelVersion.version == version)
    ).scalar_one_or_none()
    if target is None or not target.artifact_path:
        raise LookupError(f"no rollback artifact for {version}")
    if target.status == "deployed":
        raise LookupError(f"{version} is already deployed")
    deploy(session, target, reason=f"Manual rollback to {version}", now=now, action="rollback")
    return target


def prune(session: Session, kind: str, keep: int, now: datetime) -> None:
    """Keep the newest ``keep`` artifacts of a kind, none retired for over 30 days.

    Old artifacts are deleted, not just hidden: a deleted account's influence on
    item factors ends when the last version trained with their data is pruned
    (docs/PRIVACY.md)."""
    versions = session.execute(
        select(ModelVersion)
        .where(ModelVersion.kind == kind, ModelVersion.artifact_path.is_not(None))
        .order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc())
    ).scalars()
    for i, v in enumerate(versions):
        too_old = v.retired_at is not None and now - v.retired_at > RETIRED_ARTIFACT_MAX_AGE
        if v.status != "deployed" and (i >= keep or too_old):
            store.remove(v.artifact_path)
            v.artifact_path = None
    session.flush()
