"""segment emotion preset (M18)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("segments", sa.Column("emotion", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("segments", "emotion")
