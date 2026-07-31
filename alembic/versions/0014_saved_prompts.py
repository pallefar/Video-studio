"""saved prompts — the user's prompt library (M27 prompt intelligence)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_prompts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("negative", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("saved_prompts")
