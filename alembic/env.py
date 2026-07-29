from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import schema.models  # noqa: F401 — populates SQLModel.metadata

# Migrations target Postgres at runtime. Migration 0001 uses only generic
# SQLAlchemy types so it also runs on SQLite for tests; future ALTERs may be
# Postgres-only — from then on, rely on the CI job with a Postgres service.

config = context.config
target_metadata = SQLModel.metadata


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from pipeline_core.settings import Settings

    return Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
