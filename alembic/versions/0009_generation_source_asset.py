"""generation source asset — the M13 provenance chain link

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table: SQLite cannot ALTER-in a foreign-keyed column; on
    # Postgres this degrades to plain ALTERs.
    with op.batch_alter_table("generations") as batch:
        batch.add_column(sa.Column("source_asset_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_generations_source_asset", "assets", ["source_asset_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("generations") as batch:
        batch.drop_constraint("fk_generations_source_asset", type_="foreignkey")
        batch.drop_column("source_asset_id")
