"""identities + identity link on generations (M17)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TRAINING_STATUS = sa.Enum(
    "untrained",
    "queued",
    "training",
    "trained",
    "failed",
    name="identitytrainingstatus",
    native_enum=False,
    length=16,
)


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("reference_asset_ids", sa.JSON(), nullable=False),
        sa.Column("consent_recorded_by", sa.String(), nullable=True),
        sa.Column("consent_at", sa.DateTime(), nullable=True),
        sa.Column("consent_note", sa.String(), nullable=True),
        sa.Column("training_status", _TRAINING_STATUS, nullable=False),
        sa.Column("lora_uri", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_identity_name"),
    )
    # batch_alter_table: SQLite cannot ALTER-in a foreign-keyed column; on
    # Postgres this degrades to plain ALTERs.
    with op.batch_alter_table("generations") as batch:
        batch.add_column(sa.Column("identity_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_generations_identity", "identities", ["identity_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("generations") as batch:
        batch.drop_constraint("fk_generations_identity", type_="foreignkey")
        batch.drop_column("identity_id")
    op.drop_table("identities")
