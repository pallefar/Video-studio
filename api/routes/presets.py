from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.generation import enqueue_generation
from pipeline_core.presets import (
    CAMERA_PRESETS,
    MAX_STACK,
    PresetError,
    compose,
    kind_for,
    validate_stack,
)
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from schema.models import CameraPresetRead, Generation, GenerationRead, GenerationTarget

router = APIRouter(prefix="/presets", tags=["presets"])

DEFAULT_PROVIDER = "local"
DEFAULT_MODEL = "wan2.2-fun-camera"


@router.get("", response_model=list[CameraPresetRead])
async def list_presets():
    return CAMERA_PRESETS


class PresetGenerateRequest(BaseModel):
    preset_ids: list[str] = Field(min_length=1, max_length=MAX_STACK)
    subject: str = Field(min_length=2)
    image_uri: str | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    fallback: list[GenerationTarget] = []


@router.post("/generate", response_model=GenerationRead, status_code=201)
async def generate_from_presets(
    body: PresetGenerateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        presets = validate_stack(body.preset_ids)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt, params = compose(presets, body.subject)
    kind = kind_for(body.image_uri)
    if body.image_uri:
        params["image_uri"] = body.image_uri

    try:
        registry.resolve(body.provider, body.model, kind)
        for target in body.fallback:
            registry.resolve(target.provider, target.model, kind)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=kind,
        prompt=prompt,
        params=params,
        fallback=[target.model_dump() for target in body.fallback],
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation
