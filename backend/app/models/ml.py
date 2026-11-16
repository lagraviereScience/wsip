"""Model registry: versions, training runs, evaluations, deployments (spec §24, §26).

Artifacts live on the ``models`` volume; the database keeps their metadata, the
dataset statistics they were trained on, their evaluation results, and an
append-only deployment history for rollback. Artifacts contain item factors only:
no per-user rows (see docs/PRIVACY.md, "Training data").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models._common import CreatedAt, TimestampTZ


class TrainingRun(Base):
    __tablename__ = "training_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'skipped', 'failed')", name="status"),
        Index("ix_training_runs_kind_started", "kind", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # "collaborative"
    status: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual
    started_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    dataset_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    decision: Mapped[str | None] = mapped_column(Text)  # why deployed / skipped / kept
    error: Mapped[str | None] = mapped_column(Text)
    # The evaluation report (also written as Markdown next to the artifacts).
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    report_path: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'deployed', 'rejected', 'retired')", name="status"
        ),
        Index(
            "uq_model_versions_one_deployed_per_kind",
            "kind",
            unique=True,
            postgresql_where=text("status = 'deployed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    training_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_runs.id", ondelete="SET NULL")
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dataset_stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    # Which feature or signal definitions the model expects (serving checks it).
    feature_schema_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[CreatedAt]  # training timestamp
    deployed_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    retired_at: Mapped[datetime | None] = mapped_column(TimestampTZ)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("training_run_id", "algorithm", "split", "metric"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    training_run_id: Mapped[int] = mapped_column(ForeignKey("training_runs.id", ondelete="CASCADE"))
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    algorithm: Mapped[str] = mapped_column(String(32))
    split: Mapped[str] = mapped_column(String(16))  # warm | cold_item
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    n_users: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]


class ModelDeploymentHistory(Base):
    __tablename__ = "model_deployment_history"
    __table_args__ = (CheckConstraint("action IN ('deploy', 'rollback', 'retire')", name="action"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    previous_model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]


class AccountDeletion(Base):
    """That an account was deleted, and when. No identifier of any kind is kept.

    The training pipeline retrains after deletions so the deployed model stops
    reflecting deleted players as soon as a new model passes its gates."""

    __tablename__ = "account_deletions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    deleted_at: Mapped[CreatedAt]


class ModelMonitoringReport(Base):
    """Daily production metrics of the recommendation models (spec §25, prompt 5 F)."""

    __tablename__ = "model_monitoring_reports"
    __table_args__ = (UniqueConstraint("day", "window_days"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    window_days: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    alerts: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[CreatedAt]
