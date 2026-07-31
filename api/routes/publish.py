from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import _get_or_404, get_dispatcher
from api.validators.compliance import ComplianceError, check_publishable
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_CPU, stage_key
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
    job_id: uuid.UUID,
    body: PublishRecordCreate,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
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
    dispatcher.enqueue(
        QUEUE_CPU, "worker_cpu.stages.publish_stage", str(job.id),
        job_key=stage_key(job.id, "publish"),
    )
    return record


@router.get("/jobs/{job_id}/publish", response_model=PublishRecordRead)
async def get_publish_record(job_id: uuid.UUID, session: Session = Depends(get_session)):
    record = session.exec(select(PublishRecord).where(PublishRecord.job_id == job_id)).first()
    if record is None:
        raise HTTPException(status_code=404, detail="no publish record for job")
    return record


_VIDEO_SUFFIXES = ("mp4", "mov", "webm", "mkv")


@router.post("/assets/{asset_id}/publish", response_model=PublishRecordRead, status_code=201)
async def publish_asset(
    asset_id: uuid.UUID,
    body: PublishRecordCreate,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Publish a library video asset (timeline/storyboard exports) through
    the same gates as avatar jobs: C4 provenance first, C5 human review
    required (reviewed_by), the worker uploads private-always. Re-POSTing
    an unpublished record re-enqueues the upload instead of duplicating."""
    from schema.models import Asset

    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    if asset.uri.rsplit(".", 1)[-1].lower() not in _VIDEO_SUFFIXES:
        raise HTTPException(status_code=422, detail="only video assets can publish")

    record = session.exec(
        select(PublishRecord).where(PublishRecord.asset_id == asset_id)
    ).first()
    if record is not None:
        if record.youtube_id:
            raise HTTPException(status_code=409, detail="asset already published")
    else:
        record = PublishRecord(
            asset_id=asset.id,
            altered_content=body.altered_content,
            reviewed_by=body.reviewed_by,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
    dispatcher.enqueue(
        QUEUE_CPU, "worker_cpu.stages.publish_asset_stage", str(asset.id),
        job_key=stage_key(asset.id, "publish"),
    )
    return record


@router.get("/assets/{asset_id}/publish", response_model=PublishRecordRead)
async def get_asset_publish_record(
    asset_id: uuid.UUID, session: Session = Depends(get_session)
):
    record = session.exec(
        select(PublishRecord).where(PublishRecord.asset_id == asset_id)
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="no publish record for asset")
    return record
