"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_JOB_STATUS = sa.Enum(
    "queued",
    "tts",
    "lipsync",
    "assemble",
    "review",
    "publishing",
    "published",
    "failed",
    "cancelled",
    name="jobstatus",
    native_enum=False,
    length=32,
)

_ASSET_ORIGIN = sa.Enum(
    "generated", "stock", "own", name="assetorigin", native_enum=False, length=16
)


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reference_audio_uri", sa.String(), nullable=False),
        sa.Column("embedding_uri", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_voice_name_version"),
    )
    op.create_table(
        "base_loops",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_uri", sa.String(), nullable=False),
        sa.Column("latents_uri", sa.String(), nullable=True),
        sa.Column("bbox_uri", sa.String(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("seam_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "render_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("script", sa.String(), nullable=False),
        sa.Column("voice_profile_id", sa.Uuid(), sa.ForeignKey("voice_profiles.id"), nullable=False),
        sa.Column("base_loop_id", sa.Uuid(), sa.ForeignKey("base_loops.id"), nullable=False),
        sa.Column("status", _JOB_STATUS, nullable=False),
        sa.Column("watermark", sa.JSON(), nullable=False),
        sa.Column("publish", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("render_jobs.id"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("pause_after_ms", sa.Integer(), nullable=False),
        sa.Column("audio_uri", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.UniqueConstraint("job_id", "idx", name="uq_segment_job_idx"),
    )
    op.create_table(
        "publish_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # C4: publish requires a provenance record — job_id is NOT NULL and unique.
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("render_jobs.id"), nullable=False, unique=True),
        sa.Column("altered_content", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("youtube_id", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("origin", _ASSET_ORIGIN, nullable=False),
        sa.Column("uri", sa.String(), nullable=False),
        sa.Column("caption", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("has_identifiable_people", sa.Boolean(), nullable=False),
        sa.Column("license", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("assets")
    op.drop_table("publish_records")
    op.drop_table("segments")
    op.drop_table("render_jobs")
    op.drop_table("base_loops")
    op.drop_table("voice_profiles")
