"""projects, project_assets, project links on generations/storyboards

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "project_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.UniqueConstraint("project_id", "asset_id", name="uq_project_asset"),
    )
    # batch_alter_table: SQLite cannot ALTER-in a foreign-keyed column; on
    # Postgres this degrades to plain ALTERs.
    with op.batch_alter_table("generations") as batch:
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_generations_project", "projects", ["project_id"], ["id"])
    with op.batch_alter_table("storyboards") as batch:
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_storyboards_project", "projects", ["project_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("storyboards") as batch:
        batch.drop_constraint("fk_storyboards_project", type_="foreignkey")
        batch.drop_column("project_id")
    with op.batch_alter_table("generations") as batch:
        batch.drop_constraint("fk_generations_project", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_table("project_assets")
    op.drop_table("projects")
