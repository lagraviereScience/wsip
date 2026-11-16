"""Baseline: database-level conventions.

Establishes the migration chain. Pins the database's default time zone to UTC so
every session, including ad-hoc psql sessions, reads and writes UTC timestamps.
The relational schema itself is introduced in later revisions.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('ALTER DATABASE %I SET timezone TO ''UTC''', current_database()); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('ALTER DATABASE %I RESET timezone', current_database()); "
        "END $$;"
    )
