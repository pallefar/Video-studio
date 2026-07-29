"""timeline documents (M15 editor)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timeline_docs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("storyboard_id", sa.Uuid(), sa.ForeignKey("storyboards.id"), nullable=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("timeline_docs")
