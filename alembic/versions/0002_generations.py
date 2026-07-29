"""generation provider layer

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_GENERATION_KIND = sa.Enum(
    "text_to_video", "image_to_video", "image", "upscale",
    name="generationkind", native_enum=False, length=32,
)

_GENERATION_STATUS = sa.Enum(
    "queued", "running", "succeeded", "failed",
    name="generationstatus", native_enum=False, length=16,
)


def upgrade() -> None:
    op.create_table(
        "generations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("kind", _GENERATION_KIND, nullable=False),
        sa.Column("prompt", sa.String(), nullable=False),
        sa.Column("status", _GENERATION_STATUS, nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("fallback", sa.JSON(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("generations")
