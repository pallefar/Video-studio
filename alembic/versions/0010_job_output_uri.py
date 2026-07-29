"""render job output uri (M4 assembled render)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("render_jobs", sa.Column("output_uri", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("render_jobs", "output_uri")
