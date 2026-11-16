"""Alembic environment.

Connects with the schema-owning migration role (DB_MIGRATION_USER) so that the
runtime application role can stay limited to data manipulation.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.base import Base

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url(migration=True).render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        settings.database_url(migration=True),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10, "application_name": "wdywtp-migrations"},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
