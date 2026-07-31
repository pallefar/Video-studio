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


class GenerationKind(str, Enum):
    text_to_video = "text_to_video"
    image_to_video = "image_to_video"
    video_to_video = "video_to_video"  # VFX restyle lane (M13)
    image = "image"
    upscale = "upscale"
    music = "music"  # ACE-Step music beds (M18)


class GenerationStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class VideoFormat(str, Enum):
    long = "long"      # 16:9 1920x1080, full-length
    short = "short"    # 9:16 1080x1920, <= 60 s (Shorts/Reels/TikTok)


class ProjectKind(str, Enum):
    """What the project produces — one studio, many production types."""

    video = "video"    # channel/social videos (the original flow)
    movie = "movie"    # long-form, multi-scene film work
    game = "game"      # game dev assets: sprites, textures, cutscenes, trailers
    other = "other"    # anything else the pipeline serves


class IdentityTrainingStatus(str, Enum):
    untrained = "untrained"
    queued = "queued"
    training = "training"
    trained = "trained"
    failed = "failed"


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
    # Loop preprocessing results (M2): VFR sources are rejected at ingest;
    # a seam pop switches playback to the ping-pong variant.
    vfr_ratio: Optional[float] = None
    seam_score: Optional[float] = None
    ping_pong: bool = False
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class BaseLoopCreate(BaseLoopBase):
    pass


class BaseLoopRead(BaseLoopBase):
    id: uuid.UUID
    vfr_ratio: Optional[float] = None
    seam_score: Optional[float] = None
    ping_pong: bool = False
    error: Optional[str] = None
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
    # Assembled render (M4): set when assemble completes; feeds the M7 preview.
    output_uri: Optional[str] = None
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
    # Speak-style delivery preset (M18); validated against
    # pipeline_core.emotions at the API edge. None = neutral.
    emotion: Optional[str] = None


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
    output_uri: Optional[str] = None
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
    """C4 provenance. Exactly one subject: an avatar RenderJob (the M6 flow)
    OR a library asset (timeline/storyboard exports) — enforced by a DB
    check constraint (migration 0013) and the publish routes."""

    __tablename__ = "publish_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="render_jobs.id", nullable=True, unique=True
    )
    asset_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="assets.id", nullable=True, unique=True
    )
    youtube_id: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class PublishRecordCreate(PublishRecordBase):
    pass


class PublishRecordRead(PublishRecordBase):
    id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    asset_id: Optional[uuid.UUID] = None
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
# Generation — one provider-layer generation request (roadmap-v2 §3, M10)
# ---------------------------------------------------------------------------


class GenerationTarget(BaseModel):
    """One (provider, model) candidate; a request may carry an ordered chain."""

    provider: str
    model: str


class LoraRef(BaseModel):
    """A LoRA a preset depends on. Civitai LoRAs carry individual licences —
    each must be audited for commercial use before a preset may ship it."""

    name: str
    weights_uri: str
    license: str
    license_audited: bool = False


class CameraPresetRead(BaseModel):
    """One-click camera move (Higgsfield-style preset-first UX, M11)."""

    id: str
    label: str
    description: str
    category: str
    motion_code: str
    prompt_template: str
    stackable: bool = True
    loras: list[LoraRef] = []


class StyleTemplateRead(BaseModel):
    """A curated look applied consistently across a storyboard's shots
    ('Soul preset' equivalent): prompt suffix now, grade/LUT params at M16."""

    id: str
    label: str
    description: str
    prompt_suffix: str
    params: dict = {}


class EffectPresetRead(BaseModel):
    """One-click VFX applied to existing footage over the VACE v2v lane
    (M13); stacks with camera presets — the Higgsfield 'Mix' mechanic."""

    id: str
    label: str
    description: str
    category: str
    prompt_template: str
    stackable: bool = True


# ---------------------------------------------------------------------------
# Project — the container: asset center first, video center after (M20).
# Assets link many-to-many so one asset serves any number of projects and
# stands alone for social posting.
# ---------------------------------------------------------------------------


class ProjectBase(SQLModel):
    title: str
    description: Optional[str] = None
    kind: ProjectKind = Field(
        default=ProjectKind.video,
        sa_column=Column(sa.Enum(ProjectKind, native_enum=False, length=16), nullable=False),
    )


class Project(ProjectBase, table=True):
    __tablename__ = "projects"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectAsset(SQLModel, table=True):
    __tablename__ = "project_assets"
    __table_args__ = (UniqueConstraint("project_id", "asset_id", name="uq_project_asset"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="projects.id", nullable=False)
    asset_id: uuid.UUID = Field(foreign_key="assets.id", nullable=False)


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    asset_count: int = 0
    storyboard_count: int = 0


# ---------------------------------------------------------------------------
# Storyboard + Shot — per-video planning object; feeds the M15/M16 studio
# ---------------------------------------------------------------------------


class StoryboardBase(SQLModel):
    title: str
    format: VideoFormat = Field(
        default=VideoFormat.long,
        sa_column=Column(sa.Enum(VideoFormat, native_enum=False, length=16), nullable=False),
    )
    style_id: Optional[str] = None
    project_id: Optional[uuid.UUID] = Field(default=None, foreign_key="projects.id")


class Storyboard(StoryboardBase, table=True):
    __tablename__ = "storyboards"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StoryboardCreate(StoryboardBase):
    pass


class ShotBase(SQLModel):
    # non-negative: the reorder endpoint parks shots on negative idx values
    # mid-renumber, so user-supplied idx must never live there
    idx: int = Field(ge=0)
    subject: str
    preset_ids: list[str] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    duration_target_ms: int = 5000
    notes: Optional[str] = None


class Shot(ShotBase, table=True):
    __tablename__ = "shots"
    __table_args__ = (UniqueConstraint("storyboard_id", "idx", name="uq_shot_board_idx"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    storyboard_id: uuid.UUID = Field(foreign_key="storyboards.id", nullable=False)
    generation_id: Optional[uuid.UUID] = Field(default=None, foreign_key="generations.id")
    asset_id: Optional[uuid.UUID] = Field(default=None, foreign_key="assets.id")


class ShotCreate(ShotBase):
    # Use an existing library/project asset as the shot instead of generating.
    asset_id: Optional[uuid.UUID] = None


class ShotRead(ShotBase):
    id: uuid.UUID
    storyboard_id: uuid.UUID
    generation_id: Optional[uuid.UUID] = None
    asset_id: Optional[uuid.UUID] = None
    generation_status: Optional[GenerationStatus] = None


class StoryboardRead(StoryboardBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    shots: list[ShotRead] = []


class GenerationBase(SQLModel):
    provider: str
    model: str
    kind: GenerationKind
    prompt: str


class Generation(GenerationBase, table=True):
    __tablename__ = "generations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: GenerationStatus = Field(
        default=GenerationStatus.queued,
        sa_column=Column(sa.Enum(GenerationStatus, native_enum=False, length=16), nullable=False),
    )
    params: Optional[dict] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    fallback: Optional[list[dict]] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    external_id: Optional[str] = None
    cost: Optional[float] = None
    error: Optional[str] = None
    asset_id: Optional[uuid.UUID] = Field(default=None, foreign_key="assets.id")
    project_id: Optional[uuid.UUID] = Field(default=None, foreign_key="projects.id")
    # Face-bearing generation: set only after the C6 consent gate has passed.
    identity_id: Optional[uuid.UUID] = Field(default=None, foreign_key="identities.id")
    # v2v/upscale (M13): the library asset this generation derives from —
    # the provenance chain walks output asset -> generation -> source asset.
    source_asset_id: Optional[uuid.UUID] = Field(default=None, foreign_key="assets.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationCreate(GenerationBase):
    params: Optional[dict] = None
    fallback: list[GenerationTarget] = []
    project_id: Optional[uuid.UUID] = None
    identity_id: Optional[uuid.UUID] = None
    # M18: enhance the prompt before generation; both prompts are recorded
    # (raw in params.prompt_raw, enhanced as the generation prompt).
    enhance: bool = False


class GenerationRead(GenerationBase):
    id: uuid.UUID
    status: GenerationStatus
    params: Optional[dict] = None
    fallback: Optional[list[dict]] = None
    external_id: Optional[str] = None
    cost: Optional[float] = None
    error: Optional[str] = None
    asset_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    identity_id: Optional[uuid.UUID] = None
    source_asset_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Identity — "Soul ID" equivalent (M17). Identity training and face-bearing
# generation require recorded consent (C6, roadmap-v2 §8) — structural, like
# C1–C5: enforced in api/validators/compliance.py at the API edge and again
# in the wan-lane worker. No face-swap of third parties.
# ---------------------------------------------------------------------------


class IdentityBase(SQLModel):
    name: str
    description: Optional[str] = None


class Identity(IdentityBase, table=True):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("name", name="uq_identity_name"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Library assets (origin='own') used as training references.
    reference_asset_ids: list[str] = Field(
        default_factory=list, sa_column=Column(sa.JSON, nullable=False)
    )
    # Consent is append-once: recorded via POST /identities/{id}/consent and
    # never editable afterwards. Both fields set together, or neither.
    consent_recorded_by: Optional[str] = None
    consent_at: Optional[datetime] = None
    consent_note: Optional[str] = None
    training_status: IdentityTrainingStatus = Field(
        default=IdentityTrainingStatus.untrained,
        sa_column=Column(sa.Enum(IdentityTrainingStatus, native_enum=False, length=16), nullable=False),
    )
    lora_uri: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class IdentityCreate(IdentityBase):
    reference_asset_ids: list[uuid.UUID] = []


class ConsentRecord(BaseModel):
    """One person's recorded consent to train and use their likeness."""

    recorded_by: str
    note: Optional[str] = None

    @field_validator("recorded_by")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("C6: consent must name who recorded it")
        return v.strip()


class IdentityRead(IdentityBase):
    id: uuid.UUID
    reference_asset_ids: list[uuid.UUID] = []
    consent_recorded_by: Optional[str] = None
    consent_at: Optional[datetime] = None
    consent_note: Optional[str] = None
    has_consent: bool = False
    training_status: IdentityTrainingStatus
    lora_uri: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Metrics — every stage logs its duration; throughput regressions are how
# thermal throttling shows up (v1 convention, docs/psd.md §7).
# ---------------------------------------------------------------------------


class SavedPromptBase(SQLModel):
    """M27: the user's prompt library — saved by hand, distilled from the
    catalog, or reverse-engineered from a library asset."""

    title: str
    text: str
    kind: str = "video"  # video | image | music
    negative: Optional[str] = None
    source: str = "manual"  # manual | reverse | catalog


class SavedPrompt(SavedPromptBase, table=True):
    __tablename__ = "saved_prompts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tags: Optional[list[str]] = Field(default=None, sa_column=Column(sa.JSON, nullable=True))
    asset_id: Optional[uuid.UUID] = Field(default=None, foreign_key="assets.id")
    created_at: datetime = Field(default_factory=utcnow)


class SavedPromptCreate(SavedPromptBase):
    tags: Optional[list[str]] = None
    asset_id: Optional[uuid.UUID] = None


class SavedPromptRead(SavedPromptBase):
    id: uuid.UUID
    tags: Optional[list[str]] = None
    asset_id: Optional[uuid.UUID] = None
    created_at: datetime


class Metric(SQLModel, table=True):
    __tablename__ = "metrics"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stage: str
    ref: str
    duration_ms: int
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Timeline documents — the M15 editor's data model, OTIO-modelled:
# tracks hold clips positioned on the timeline (start_ms) with a trim range
# into their source (in_ms/out_ms). Track 0 is the base video track.
# ---------------------------------------------------------------------------


class TimelineClip(BaseModel):
    id: str
    asset_id: str
    start_ms: int
    in_ms: int = 0
    out_ms: int

    @model_validator(mode="after")
    def _valid_range(self) -> "TimelineClip":
        if self.start_ms < 0 or self.in_ms < 0:
            raise ValueError("clip times must be non-negative")
        if self.out_ms <= self.in_ms:
            raise ValueError("clip out_ms must be greater than in_ms")
        return self


class AudioClip(BaseModel):
    """Music/audio-bed clip. Ducked under shot audio by default (M18);
    fade_in/out are applied by the M16 compiler before gain/delay."""

    id: str
    asset_id: str
    start_ms: int
    in_ms: int = 0
    out_ms: int
    gain: float = 1.0
    duck: bool = True
    fade_in_ms: int = 0
    fade_out_ms: int = 0

    @model_validator(mode="after")
    def _valid_range(self) -> "AudioClip":
        if self.start_ms < 0 or self.in_ms < 0:
            raise ValueError("clip times must be non-negative")
        if self.out_ms <= self.in_ms:
            raise ValueError("clip out_ms must be greater than in_ms")
        if not 0.0 <= self.gain <= 4.0:
            raise ValueError("gain must be within [0, 4]")
        if self.fade_in_ms < 0 or self.fade_out_ms < 0:
            raise ValueError("fades must be non-negative")
        if self.fade_in_ms + self.fade_out_ms > self.out_ms - self.in_ms:
            raise ValueError("fades cannot exceed the clip length")
        return self


class TextClip(BaseModel):
    id: str
    text: str
    start_ms: int
    end_ms: int
    y_pct: float = 0.8

    @model_validator(mode="after")
    def _valid_range(self) -> "TextClip":
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("text clip needs end_ms > start_ms >= 0")
        if not 0.0 <= self.y_pct <= 1.0:
            raise ValueError("y_pct must be within [0, 1]")
        return self


class TimelineDocument(BaseModel):
    format: VideoFormat = VideoFormat.long
    transition_ms: int = 0
    video_tracks: list[list[TimelineClip]] = [[]]
    audio_tracks: list[list[AudioClip]] = []
    texts: list[TextClip] = []

    @model_validator(mode="after")
    def _no_overlaps(self) -> "TimelineDocument":
        for track in [*self.video_tracks, *self.audio_tracks]:
            ordered = sorted(track, key=lambda c: c.start_ms)
            for a, b in zip(ordered, ordered[1:]):
                if a.start_ms + (a.out_ms - a.in_ms) > b.start_ms:
                    raise ValueError(f"clips {a.id} and {b.id} overlap on the same track")
        return self


class TimelineDocBase(SQLModel):
    title: str
    storyboard_id: Optional[uuid.UUID] = Field(default=None, foreign_key="storyboards.id")
    project_id: Optional[uuid.UUID] = Field(default=None, foreign_key="projects.id")


class TimelineDoc(TimelineDocBase, table=True):
    __tablename__ = "timeline_docs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: int = 1
    doc: TimelineDocument = Field(
        default_factory=TimelineDocument,
        sa_column=Column(PydanticJSON(TimelineDocument), nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TimelineDocCreate(TimelineDocBase):
    doc: TimelineDocument = TimelineDocument()


class TimelineDocRead(TimelineDocBase):
    id: uuid.UUID
    version: int
    doc: TimelineDocument
    created_at: datetime
    updated_at: datetime


class TimelineDocSave(BaseModel):
    doc: TimelineDocument
    base_version: int


# ---------------------------------------------------------------------------
# Export manifests for the TS generator — order is the file order, keep stable
# ---------------------------------------------------------------------------

EXPORTED_ENUMS: list[type[Enum]] = [
    JobStatus,
    AssetOrigin,
    GenerationKind,
    GenerationStatus,
    VideoFormat,
    IdentityTrainingStatus,
    ProjectKind,
]

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
    GenerationTarget,
    GenerationCreate,
    GenerationRead,
    LoraRef,
    CameraPresetRead,
    StyleTemplateRead,
    EffectPresetRead,
    IdentityCreate,
    IdentityRead,
    ConsentRecord,
    ShotCreate,
    ShotRead,
    StoryboardCreate,
    StoryboardRead,
    ProjectCreate,
    ProjectRead,
    TimelineClip,
    AudioClip,
    TextClip,
    TimelineDocument,
    TimelineDocCreate,
    TimelineDocRead,
    TimelineDocSave,
]
