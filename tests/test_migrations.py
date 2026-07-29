"""Migration smoke test. 0001 uses only generic SQLAlchemy types, so it runs
against SQLite here; CI additionally runs it against a real Postgres service.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "voice_profiles",
    "base_loops",
    "render_jobs",
    "segments",
    "publish_records",
    "assets",
    "generations",
    "storyboards",
    "shots",
    "projects",
    "project_assets",
    "timeline_docs",
    "metrics",
}


def _config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_upgrade_head_and_downgrade(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    cfg = _config(db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= tables, f"missing: {EXPECTED_TABLES - tables}"

    command.downgrade(cfg, "base")
    tables_after = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert not (EXPECTED_TABLES & tables_after)
    engine.dispose()


def test_migration_matches_model_metadata(tmp_path: Path):
    """Every table and column SQLModel declares exists after upgrade head."""
    from sqlmodel import SQLModel

    import schema.models  # noqa: F401

    db_url = f"sqlite:///{tmp_path / 'meta.sqlite3'}"
    command.upgrade(_config(db_url), "head")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    for table in SQLModel.metadata.sorted_tables:
        migrated_cols = {c["name"] for c in inspector.get_columns(table.name)}
        model_cols = {c.name for c in table.columns}
        assert model_cols <= migrated_cols, (
            f"{table.name}: migration missing columns {model_cols - migrated_cols}"
        )
    engine.dispose()
