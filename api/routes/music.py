"""Music-bed generation (M18) — ACE-Step on the shared GPU lane, landing as
licensed-clean library assets ready for the editor's audio tracks."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.generation import enqueue_generation
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from schema.models import Generation, GenerationKind, GenerationRead, Project

router = APIRouter(prefix="/music", tags=["music"])

DEFAULT_PROVIDER = "local"
DEFAULT_MODEL = "ace-step"
# Recorded on the generated asset: ACE-Step is Apache 2.0, outputs clean for
# commercial use (roadmap-v2 §6).
ASSET_LICENSE = "Generated (ACE-Step, Apache 2.0)"
# ElevenLabs outputs: commercial use is granted by the paid plan's ToS —
# recorded per the roadmap §3 rule so the asset carries its true provenance.
ELEVENLABS_LICENSE = "Generated (ElevenLabs API, paid-plan commercial licence)"


def _license_for(provider: str, local_license: str) -> str:
    return ELEVENLABS_LICENSE if provider == "elevenlabs" else local_license


class MusicGenerateRequest(BaseModel):
    prompt: str = Field(min_length=2, description="mood/genre/instrumentation")
    duration_s: int = Field(default=60, ge=5, le=600)
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    project_id: uuid.UUID | None = None


@router.post("/generate", response_model=GenerationRead, status_code=201)
async def generate_music(
    body: MusicGenerateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        registry.resolve(body.provider, body.model, GenerationKind.music)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.music,
        prompt=body.prompt,
        params={
            "duration_s": body.duration_s,
            "purpose": "music_bed",
            "asset_license": _license_for(body.provider, ASSET_LICENSE),
        },
        project_id=body.project_id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


# --- M28: voiceover lines (Chatterbox on the render lane) -------------------

VOICE_LICENSE = "Generated (Chatterbox, MIT)"
DEFAULT_VOICE_MODEL = "chatterbox"


class VoiceoverRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    voice_profile_id: uuid.UUID | None = None
    # ElevenLabs voice id (their voice library), used when provider=elevenlabs.
    voice_id: str | None = Field(default=None, max_length=64)
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_VOICE_MODEL
    project_id: uuid.UUID | None = None


@router.post("/voice", response_model=GenerationRead, status_code=201)
async def generate_voiceover(
    body: VoiceoverRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Standalone voiceover: a spoken line landing as a library audio asset,
    ready for the editor's bed lane or a talking photo."""
    from schema.models import VoiceProfile

    try:
        registry.resolve(body.provider, body.model, GenerationKind.voice)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    params: dict = {
        "purpose": "voiceover",
        "asset_license": _license_for(body.provider, VOICE_LICENSE),
    }
    if body.voice_profile_id is not None:
        if session.get(VoiceProfile, body.voice_profile_id) is None:
            raise HTTPException(status_code=404, detail="voice profile not found")
        params["voice_profile_id"] = str(body.voice_profile_id)
    if body.voice_id:
        params["voice_id"] = body.voice_id

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.voice,
        prompt=body.text,
        params=params,
        project_id=body.project_id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation
