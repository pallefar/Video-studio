"""loop preprocessing fields (M2): vfr ratio, seam score, ping-pong, error

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("base_loops", sa.Column("vfr_ratio", sa.Float(), nullable=True))
    op.add_column("base_loops", sa.Column("seam_score", sa.Float(), nullable=True))
    op.add_column(
        "base_loops",
        sa.Column("ping_pong", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("base_loops", sa.Column("error", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("base_loops", "error")
    op.drop_column("base_loops", "ping_pong")
    op.drop_column("base_loops", "seam_score")
    op.drop_column("base_loops", "vfr_ratio")
