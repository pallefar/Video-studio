"""publish records for library assets — timeline/storyboard exports can
reach YouTube through the same C4/C5 gates as avatar jobs

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_records") as batch:
        batch.alter_column("job_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("asset_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_publish_records_asset_id", "assets", ["asset_id"], ["id"]
        )
        batch.create_unique_constraint("uq_publish_records_asset_id", ["asset_id"])
        # exactly one subject: a job or an asset, never both, never neither
        batch.create_check_constraint(
            "ck_publish_subject",
            "(job_id IS NULL) != (asset_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("publish_records") as batch:
        batch.drop_constraint("ck_publish_subject", type_="check")
        batch.drop_constraint("uq_publish_records_asset_id", type_="unique")
        batch.drop_constraint("fk_publish_records_asset_id", type_="foreignkey")
        batch.drop_column("asset_id")
        batch.alter_column("job_id", existing_type=sa.Uuid(), nullable=False)
