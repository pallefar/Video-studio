"""storyboards and shots

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_VIDEO_FORMAT = sa.Enum("long", "short", name="videoformat", native_enum=False, length=16)


def upgrade() -> None:
    op.create_table(
        "storyboards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("format", _VIDEO_FORMAT, nullable=False),
        sa.Column("style_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "shots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("storyboard_id", sa.Uuid(), sa.ForeignKey("storyboards.id"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("preset_ids", sa.JSON(), nullable=False),
        sa.Column("duration_target_ms", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("generation_id", sa.Uuid(), sa.ForeignKey("generations.id"), nullable=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.UniqueConstraint("storyboard_id", "idx", name="uq_shot_board_idx"),
    )


def downgrade() -> None:
    op.drop_table("shots")
    op.drop_table("storyboards")
