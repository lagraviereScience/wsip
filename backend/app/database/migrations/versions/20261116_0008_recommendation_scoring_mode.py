"""Scoring mode on recommendation runs (AI_GRADE).

Adds recommendation_runs.scoring_mode ('ai' | 'classic') and config_version (a
fingerprint of the scoring configuration). Existing runs were all produced by the
machine-learning engine (the only mode before this revision), so they become 'ai'.
No data is rewritten or deleted; switching modes needs no further migration.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-16 00:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendation_runs",
        sa.Column("scoring_mode", sa.String(length=16), server_default="ai", nullable=False),
    )
    op.add_column(
        "recommendation_runs", sa.Column("config_version", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_recommendation_runs_scoring_mode"),
        "recommendation_runs",
        "scoring_mode IN ('ai', 'classic')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_recommendation_runs_scoring_mode"), "recommendation_runs", type_="check"
    )
    op.drop_column("recommendation_runs", "config_version")
    op.drop_column("recommendation_runs", "scoring_mode")
