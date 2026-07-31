"""project kind — one studio, many production types (video/movie/game/other)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_PROJECT_KIND = sa.Enum(
    "video", "movie", "game", "other",
    name="projectkind", native_enum=False, length=16,
)


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("kind", _PROJECT_KIND, nullable=False, server_default="video"),
    )


def downgrade() -> None:
    op.drop_column("projects", "kind")
