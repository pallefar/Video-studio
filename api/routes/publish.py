from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import _get_or_404
from api.validators.compliance import ComplianceError, check_publishable
from schema.models import (
    JobStatus,
    PublishRecord,
    PublishRecordCreate,
    PublishRecordRead,
    utcnow,
)

router = APIRouter(tags=["publish"])


@router.post("/jobs/{job_id}/publish", response_model=PublishRecordRead, status_code=201)
async def publish_job(
    job_id: uuid.UUID, body: PublishRecordCreate, session: Session = Depends(get_session)
):
    """Move a reviewed job to publishing. C4: the provenance record is created
    in the same transaction that changes the status — publish cannot happen
    without one. The actual upload (always private, C5) is the M6 worker's job.
    """
    job = _get_or_404(session, job_id)
    try:
        check_publishable(job)
    except ComplianceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = session.exec(
        select(PublishRecord).where(PublishRecord.job_id == job_id)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="job already has a publish record")

    record = PublishRecord(
        job_id=job.id,
        altered_content=body.altered_content,
        reviewed_by=body.reviewed_by,
    )
    job.status = JobStatus.publishing
    job.updated_at = utcnow()
    session.add(record)
    session.add(job)
    session.commit()
    session.refresh(record)
    return record


@router.get("/jobs/{job_id}/publish", response_model=PublishRecordRead)
async def get_publish_record(job_id: uuid.UUID, session: Session = Depends(get_session)):
    record = session.exec(select(PublishRecord).where(PublishRecord.job_id == job_id)).first()
    if record is None:
        raise HTTPException(status_code=404, detail="no publish record for job")
    return record
