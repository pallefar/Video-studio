from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from pipeline_core.dispatch import Dispatcher
from pipeline_core.emotions import EmotionError, emotion_params
from pipeline_core.queues import QUEUE_GPU, stage_key
from pipeline_core.segmenting import SEED_MAX, make_segments
from schema.models import (
    VALID_TRANSITIONS,
    BaseLoop,
    JobStatus,
    RenderJob,
    RenderJobCreate,
    RenderJobRead,
    Segment,
    SegmentRead,
    VoiceProfile,
    utcnow,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_dispatcher: Dispatcher | None = None


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
    return _dispatcher


def _enqueue_render(dispatcher: Dispatcher, job_id: uuid.UUID) -> None:
    dispatcher.enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )


def _get_or_404(session: Session, job_id: uuid.UUID) -> RenderJob:
    job = session.get(RenderJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _read_model(session: Session, job: RenderJob) -> RenderJobRead:
    segments = session.exec(
        select(Segment).where(Segment.job_id == job.id).order_by(Segment.idx)
    ).all()
    return RenderJobRead(
        **job.model_dump(exclude={"watermark", "publish"}),
        watermark=job.watermark,
        publish=job.publish,
        segments=[SegmentRead.model_validate(s) for s in segments],
    )


@router.post("", response_model=RenderJobRead, status_code=201)
async def create_job(
    body: RenderJobCreate,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    if session.get(VoiceProfile, body.voice_profile_id) is None:
        raise HTTPException(status_code=404, detail="voice profile not found")
    if session.get(BaseLoop, body.base_loop_id) is None:
        raise HTTPException(status_code=404, detail="base loop not found")
    job = RenderJob(
        **body.model_dump(exclude={"watermark", "publish"}),
        watermark=body.watermark,
        publish=body.publish,
    )
    session.add(job)
    session.commit()
    for segment in make_segments(job.id, job.script):
        session.add(segment)
    session.commit()
    session.refresh(job)
    _enqueue_render(dispatcher, job.id)
    return _read_model(session, job)


@router.get("", response_model=list[RenderJobRead])
async def list_jobs(session: Session = Depends(get_session)):
    jobs = session.exec(select(RenderJob).order_by(RenderJob.created_at)).all()
    return [_read_model(session, job) for job in jobs]


@router.get("/{job_id}", response_model=RenderJobRead)
async def get_job(job_id: uuid.UUID, session: Session = Depends(get_session)):
    return _read_model(session, _get_or_404(session, job_id))


class TransitionRequest(BaseModel):
    status: JobStatus
    error: str | None = None


@router.post("/{job_id}/transition", response_model=RenderJobRead)
async def transition_job(
    job_id: uuid.UUID,
    body: TransitionRequest,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    job = _get_or_404(session, job_id)
    allowed = VALID_TRANSITIONS.get(job.status, set())
    if body.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"invalid transition {job.status.value} -> {body.status.value}",
        )
    job.status = body.status
    job.error = body.error
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    if body.status == JobStatus.queued:
        # retry (failed -> queued) and re-render (review -> queued) re-enter the lane
        _enqueue_render(dispatcher, job.id)
    return _read_model(session, job)


def _get_object_store():
    from api.routes.assets import get_object_store

    return get_object_store()


@router.get("/{job_id}/preview")
async def preview_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    store=Depends(_get_object_store),
):
    """Presigned URL for the assembled render (M7 preview-before-publish).
    Available once M4's assemble stage has produced final.mp4."""
    job = _get_or_404(session, job_id)
    if not job.output_uri:
        raise HTTPException(status_code=404, detail="no assembled output yet")
    _, key = store.parse_uri(job.output_uri)
    return {"url": store.presign_get(key), "uri": job.output_uri}


class SegmentRerenderRequest(BaseModel):
    """Re-render one segment (the retry unit). The pinned seed is kept unless
    reseed asks for a fresh take; emotion (M18) changes delivery only when
    provided — an explicit null resets to neutral."""

    emotion: str | None = None
    reseed: bool = False


@router.post("/{job_id}/segments/{idx}/rerender", response_model=RenderJobRead)
async def rerender_segment(
    job_id: uuid.UUID,
    idx: int,
    body: SegmentRerenderRequest,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    import secrets

    job = _get_or_404(session, job_id)
    if job.status != JobStatus.review:
        raise HTTPException(
            status_code=409, detail="per-segment re-render requires the job to be in review"
        )
    segment = session.exec(
        select(Segment).where(Segment.job_id == job_id, Segment.idx == idx)
    ).first()
    if segment is None:
        raise HTTPException(status_code=404, detail=f"segment {idx} not found")

    if "emotion" in body.model_fields_set:
        try:
            emotion_params(body.emotion)  # validate against the registry
        except EmotionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        segment.emotion = body.emotion
    if body.reseed:
        segment.seed = secrets.randbelow(SEED_MAX)

    # clearing the audio makes tts_stage re-render exactly this segment
    segment.audio_uri = None
    segment.duration_ms = None
    session.add(segment)

    job.status = JobStatus.queued
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    _enqueue_render(dispatcher, job.id)
    return _read_model(session, job)
