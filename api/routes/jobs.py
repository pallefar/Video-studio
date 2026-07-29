from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
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
async def create_job(body: RenderJobCreate, session: Session = Depends(get_session)):
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
    session.refresh(job)
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
    job_id: uuid.UUID, body: TransitionRequest, session: Session = Depends(get_session)
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
    return _read_model(session, job)
