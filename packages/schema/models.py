"""Pydantic/SQLModel entities — the single source of truth for the pipeline.

Layout per entity: XBase holds the shared fields and validators (written once),
X(XBase, table=True) adds keys and storage concerns, XCreate/XRead are the API
edge shapes. SQLModel table classes skip Pydantic validation on instantiation,
so compliance validators are guaranteed only at the API edge (Create schemas)
and in api/validators/compliance.py at the publish gate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

import sqlalchemy as sa
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Column, Field, SQLModel, UniqueConstraint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums and the job state machine
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    queued = "queued"
    tts = "tts"
    lipsync = "lipsync"
    assemble = "assemble"
    review = "review"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    cancelled = "cancelled"


class AssetOrigin(str, Enum):
    generated = "generated"
    stock = "stock"
    own = "own"


# Stage names used for idempotency keys — see pipeline_core.queues.stage_key.
STAGES: tuple[str, ...] = ("tts", "lipsync", "assemble", "captions", "watermark", "publish")

# review -> queued is the per-segment re-render loop; failed -> queued is retry.
VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.queued: {JobStatus.tts, JobStatus.failed, JobStatus.cancelled},
    JobStatus.tts: {JobStatus.lipsync, JobStatus.failed, JobStatus.cancelled},
    JobStatus.lipsync: {JobStatus.assemble, JobStatus.failed, JobStatus.cancelled},
    JobStatus.assemble: {JobStatus.review, JobStatus.failed, JobStatus.cancelled},
    JobStatus.review: {JobStatus.publishing, JobStatus.queued, JobStatus.cancelled},
    JobStatus.publishing: {JobStatus.published, JobStatus.failed},
    JobStatus.failed: {JobStatus.queued},
    JobStatus.published: set(),
    JobStatus.cancelled: set(),
}


# ---------------------------------------------------------------------------
# Embedded configs (JSON columns on RenderJob) — compliance lives here
# ---------------------------------------------------------------------------


class WatermarkConfig(BaseModel):
    """C1: visible 'Made with AI' watermark, full duration, bottom-right."""

    text: str = "Made with AI"
    position: Literal["bottom_right"] = "bottom_right"
    persistent: bool = True

    @field_validator("persistent")
    @classmethod
    def _must_be_persistent(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("C1: watermark.persistent must be true — the watermark runs full duration")
        return v


class PublishConfig(BaseModel):
    """C2: altered_content always set. C5: visibility can only ever be private."""

    altered_content: bool = True
    visibility: Literal["private"] = "private"

    @field_validator("altered_content")
    @classmethod
    def _must_disclose(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("C2: publish.altered_content must be true on every upload")
        return v


class PydanticJSON(sa.types.TypeDecorator):
    """Stores a Pydantic model in a portable JSON column (SQLite and Postgres)."""

    impl = sa.JSON
    cache_ok = True

    def __init__(self, model_cls: type[BaseModel]):
        super().__init__()
        self.model_cls = model_cls

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.model_cls.model_validate(value)


# ---------------------------------------------------------------------------
# VoiceProfile — immutable once referenced by a job (enforced in routes)
# ---------------------------------------------------------------------------


class VoiceProfileBase(SQLModel):
    name: str
    engine: str = "chatterbox"
    version: int = 1
    reference_audio_uri: str
    embedding_uri: Optional[str] = None


class VoiceProfile(VoiceProfileBase, table=True):
    __tablename__ = "voice_profiles"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_voice_name_version"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class VoiceProfileCreate(VoiceProfileBase):
    pass


class VoiceProfileRead(VoiceProfileBase):
    id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# BaseLoop — immutable once referenced by a job (enforced in routes)
# ---------------------------------------------------------------------------


class BaseLoopBase(SQLModel):
    name: str
    source_uri: str
    latents_uri: Optional[str] = None
    bbox_uri: Optional[str] = None
    fps: float
    frame_count: int
    seam_index: Optional[int] = None


class BaseLoop(BaseLoopBase, table=True):
    __tablename__ = "base_loops"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class BaseLoopCreate(BaseLoopBase):
    pass


class BaseLoopRead(BaseLoopBase):
    id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# RenderJob + Segment
# ---------------------------------------------------------------------------


class RenderJobBase(SQLModel):
    title: str
    script: str
    voice_profile_id: uuid.UUID = Field(foreign_key="voice_profiles.id")
    base_loop_id: uuid.UUID = Field(foreign_key="base_loops.id")


class RenderJob(RenderJobBase, table=True):
    __tablename__ = "render_jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: JobStatus = Field(
        default=JobStatus.queued,
        sa_column=Column(sa.Enum(JobStatus, native_enum=False, length=32), nullable=False),
    )
    watermark: WatermarkConfig = Field(
        default_factory=WatermarkConfig,
        sa_column=Column(PydanticJSON(WatermarkConfig), nullable=False),
    )
    publish: PublishConfig = Field(
        default_factory=PublishConfig,
        sa_column=Column(PydanticJSON(PublishConfig), nullable=False),
    )
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RenderJobCreate(RenderJobBase):
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)


class SegmentBase(SQLModel):
    idx: int
    text: str
    pause_after_ms: int = 0
    audio_uri: Optional[str] = None
    duration_ms: Optional[int] = None
    seed: Optional[int] = None


class Segment(SegmentBase, table=True):
    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("job_id", "idx", name="uq_segment_job_idx"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="render_jobs.id")


class SegmentRead(SegmentBase):
    id: uuid.UUID
    job_id: uuid.UUID


class RenderJobRead(RenderJobBase):
    id: uuid.UUID
    status: JobStatus
    watermark: WatermarkConfig
    publish: PublishConfig
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    segments: list[SegmentRead] = []


# ---------------------------------------------------------------------------
# PublishRecord — provenance audit trail (C4: publish requires one)
# ---------------------------------------------------------------------------


class PublishRecordBase(SQLModel):
    altered_content: bool = True
    reviewed_by: str

    @field_validator("altered_content")
    @classmethod
    def _must_disclose(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("C2: provenance record must attest altered_content")
        return v


class PublishRecord(PublishRecordBase, table=True):
    __tablename__ = "publish_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="render_jobs.id", nullable=False, unique=True)
    youtube_id: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class PublishRecordCreate(PublishRecordBase):
    pass


class PublishRecordRead(PublishRecordBase):
    id: uuid.UUID
    job_id: uuid.UUID
    youtube_id: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Asset — B-roll library
# ---------------------------------------------------------------------------


class AssetBase(SQLModel):
    origin: AssetOrigin
    uri: str
    caption: Optional[str] = None
    duration_ms: Optional[int] = None
    # Defaults to True: stock footage is assumed to contain identifiable people
    # until a human clears it. The resolver must never select a flagged asset.
    has_identifiable_people: bool = True
    license: Optional[str] = None
    source_url: Optional[str] = None
    approved: bool = False


class Asset(AssetBase, table=True):
    __tablename__ = "assets"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    embedding: Optional[list[float]] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow)


class AssetCreate(AssetBase):
    @model_validator(mode="after")
    def _stock_needs_provenance(self) -> "AssetCreate":
        if self.origin == AssetOrigin.stock and (not self.license or not self.source_url):
            raise ValueError("stock assets must persist license and source_url at ingest")
        return self


class AssetRead(AssetBase):
    id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Export manifests for the TS generator — order is the file order, keep stable
# ---------------------------------------------------------------------------

EXPORTED_ENUMS: list[type[Enum]] = [JobStatus, AssetOrigin]

EXPORTED_MODELS: list[type[SQLModel] | type[BaseModel]] = [
    WatermarkConfig,
    PublishConfig,
    VoiceProfileCreate,
    VoiceProfileRead,
    BaseLoopCreate,
    BaseLoopRead,
    SegmentRead,
    RenderJobCreate,
    RenderJobRead,
    PublishRecordCreate,
    PublishRecordRead,
    AssetCreate,
    AssetRead,
]
