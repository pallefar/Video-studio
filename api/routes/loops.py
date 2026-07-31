from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_CPU, stage_key
from schema.models import BaseLoop, BaseLoopCreate, BaseLoopRead, RenderJob

router = APIRouter(prefix="/loops", tags=["loops"])

PREPROCESS_STAGE = "worker_cpu.stages.loop_preprocess_stage"


def _enqueue_preprocess(dispatcher: Dispatcher, loop_id: uuid.UUID) -> None:
    dispatcher.enqueue(
        QUEUE_CPU, PREPROCESS_STAGE, str(loop_id),
        job_key=stage_key(loop_id, "loop_preprocess"),
    )


def _get_or_404(session: Session, loop_id: uuid.UUID) -> BaseLoop:
    loop = session.get(BaseLoop, loop_id)
    if loop is None:
        raise HTTPException(status_code=404, detail="base loop not found")
    return loop


def _is_referenced(session: Session, loop_id: uuid.UUID) -> bool:
    stmt = select(RenderJob.id).where(RenderJob.base_loop_id == loop_id).limit(1)
    return session.exec(stmt).first() is not None


@router.post("", response_model=BaseLoopRead, status_code=201)
async def create_loop(
    body: BaseLoopCreate,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    loop = BaseLoop.model_validate(body)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    # M2: VFR rejection and seam detection run at ingest, never mid-pipeline
    _enqueue_preprocess(dispatcher, loop.id)
    return loop


@router.post("/{loop_id}/preprocess", response_model=BaseLoopRead, status_code=202)
async def preprocess_loop(
    loop_id: uuid.UUID,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Re-run M2 preprocessing (e.g. after replacing the source)."""
    loop = _get_or_404(session, loop_id)
    _enqueue_preprocess(dispatcher, loop.id)
    return loop


@router.get("", response_model=list[BaseLoopRead])
async def list_loops(session: Session = Depends(get_session)):
    return session.exec(select(BaseLoop).order_by(BaseLoop.created_at)).all()


@router.get("/{loop_id}", response_model=BaseLoopRead)
async def get_loop(loop_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_or_404(session, loop_id)


@router.put("/{loop_id}", response_model=BaseLoopRead)
async def update_loop(
    loop_id: uuid.UUID, body: BaseLoopCreate, session: Session = Depends(get_session)
):
    loop = _get_or_404(session, loop_id)
    if _is_referenced(session, loop_id):
        raise HTTPException(status_code=409, detail="base loop is referenced by a job and is immutable — ingest a new loop")
    for key, value in body.model_dump().items():
        setattr(loop, key, value)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    return loop


@router.delete("/{loop_id}", status_code=204)
async def delete_loop(loop_id: uuid.UUID, session: Session = Depends(get_session)):
    loop = _get_or_404(session, loop_id)
    if _is_referenced(session, loop_id):
        raise HTTPException(status_code=409, detail="base loop is referenced by a job and cannot be deleted")
    session.delete(loop)
    session.commit()
