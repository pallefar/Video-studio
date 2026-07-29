from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from schema.models import RenderJob, VoiceProfile, VoiceProfileCreate, VoiceProfileRead

router = APIRouter(prefix="/voices", tags=["voices"])


def _get_or_404(session: Session, voice_id: uuid.UUID) -> VoiceProfile:
    voice = session.get(VoiceProfile, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="voice profile not found")
    return voice


def _is_referenced(session: Session, voice_id: uuid.UUID) -> bool:
    stmt = select(RenderJob.id).where(RenderJob.voice_profile_id == voice_id).limit(1)
    return session.exec(stmt).first() is not None


@router.post("", response_model=VoiceProfileRead, status_code=201)
async def create_voice(body: VoiceProfileCreate, session: Session = Depends(get_session)):
    voice = VoiceProfile.model_validate(body)
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.get("", response_model=list[VoiceProfileRead])
async def list_voices(session: Session = Depends(get_session)):
    return session.exec(select(VoiceProfile).order_by(VoiceProfile.created_at)).all()


@router.get("/{voice_id}", response_model=VoiceProfileRead)
async def get_voice(voice_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_or_404(session, voice_id)


@router.put("/{voice_id}", response_model=VoiceProfileRead)
async def update_voice(
    voice_id: uuid.UUID, body: VoiceProfileCreate, session: Session = Depends(get_session)
):
    voice = _get_or_404(session, voice_id)
    if _is_referenced(session, voice_id):
        # Immutable once referenced: re-cloning creates a new versioned profile.
        raise HTTPException(status_code=409, detail="voice profile is referenced by a job and is immutable — create a new version")
    for key, value in body.model_dump().items():
        setattr(voice, key, value)
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: uuid.UUID, session: Session = Depends(get_session)):
    voice = _get_or_404(session, voice_id)
    if _is_referenced(session, voice_id):
        raise HTTPException(status_code=409, detail="voice profile is referenced by a job and cannot be deleted")
    session.delete(voice)
    session.commit()
