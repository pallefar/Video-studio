"""Identity & consent — "Soul ID" equivalent (M17).

Consent is the structural gate (C6, like C1–C5): an identity can exist without
it, but training and face-bearing generation are refused until consent is
recorded. Recording is append-once — consent is never editable or revocable
through the API by design; a wrongly-recorded identity is deleted, not amended.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import get_dispatcher
from api.validators.compliance import ComplianceError, check_identity_consented
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_WAN
from schema.models import (
    Asset,
    ConsentRecord,
    Identity,
    IdentityCreate,
    IdentityRead,
    IdentityTrainingStatus,
    utcnow,
)

router = APIRouter(prefix="/identities", tags=["identities"])

TRAINING_STAGE = "worker_gpu.stages.identity_training_stage"


def _read(identity: Identity) -> IdentityRead:
    return IdentityRead(
        id=identity.id,
        name=identity.name,
        description=identity.description,
        reference_asset_ids=[uuid.UUID(a) for a in identity.reference_asset_ids],
        consent_recorded_by=identity.consent_recorded_by,
        consent_at=identity.consent_at,
        consent_note=identity.consent_note,
        has_consent=bool(identity.consent_recorded_by and identity.consent_at),
        training_status=identity.training_status,
        lora_uri=identity.lora_uri,
        error=identity.error,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )


def _get_or_404(session: Session, identity_id: uuid.UUID) -> Identity:
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="identity not found")
    return identity


@router.post("", response_model=IdentityRead, status_code=201)
async def create_identity(body: IdentityCreate, session: Session = Depends(get_session)):
    for asset_id in body.reference_asset_ids:
        if session.get(Asset, asset_id) is None:
            raise HTTPException(status_code=404, detail=f"reference asset {asset_id} not found")
    existing = session.exec(select(Identity).where(Identity.name == body.name)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"identity {body.name!r} already exists")

    identity = Identity(
        name=body.name,
        description=body.description,
        reference_asset_ids=[str(a) for a in body.reference_asset_ids],
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return _read(identity)


@router.get("", response_model=list[IdentityRead])
async def list_identities(session: Session = Depends(get_session)):
    identities = session.exec(select(Identity).order_by(Identity.created_at)).all()
    return [_read(i) for i in identities]


@router.get("/{identity_id}", response_model=IdentityRead)
async def get_identity(identity_id: uuid.UUID, session: Session = Depends(get_session)):
    return _read(_get_or_404(session, identity_id))


@router.post("/{identity_id}/consent", response_model=IdentityRead)
async def record_consent(
    identity_id: uuid.UUID, body: ConsentRecord, session: Session = Depends(get_session)
):
    identity = _get_or_404(session, identity_id)
    if identity.consent_recorded_by or identity.consent_at is not None:
        raise HTTPException(
            status_code=409, detail="consent already recorded — it is append-once, not editable"
        )
    identity.consent_recorded_by = body.recorded_by
    identity.consent_at = utcnow()
    identity.consent_note = body.note
    identity.updated_at = utcnow()
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return _read(identity)


@router.post("/{identity_id}/train", response_model=IdentityRead, status_code=202)
async def train_identity(
    identity_id: uuid.UUID,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Enqueue LoRA training on the wan lane (overnight batch, exclusive GPU
    lock). C6: refused without recorded consent."""
    identity = _get_or_404(session, identity_id)
    try:
        check_identity_consented(identity)
    except ComplianceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not identity.reference_asset_ids:
        raise HTTPException(status_code=422, detail="training needs at least one reference asset")
    if identity.training_status in (IdentityTrainingStatus.queued, IdentityTrainingStatus.training):
        raise HTTPException(status_code=409, detail="training already in progress")

    identity.training_status = IdentityTrainingStatus.queued
    identity.error = None
    identity.updated_at = utcnow()
    session.add(identity)
    session.commit()
    session.refresh(identity)
    dispatcher.enqueue(
        QUEUE_WAN, TRAINING_STAGE, str(identity.id), job_key=f"identity-train-{identity.id}"
    )
    return _read(identity)
