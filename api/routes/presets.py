from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from api.validators.compliance import ComplianceError, check_identity_consented
from pipeline_core.dispatch import Dispatcher
from pipeline_core.generation import enqueue_generation
from pipeline_core.presets import (
    CAMERA_PRESETS,
    MAX_STACK,
    MAX_TRAJECTORY_POINTS,
    RECAM_MODEL,
    UNI3C_MODEL,
    PresetError,
    TrajectoryPoint,
    compose,
    compose_reshoot,
    compose_trajectory,
    kind_for,
    validate_stack,
    validate_trajectory,
)
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from schema.models import (
    Asset,
    CameraPresetRead,
    Generation,
    GenerationKind,
    GenerationRead,
    GenerationTarget,
    Identity,
    Project,
)

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
    project_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None


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

    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    if body.identity_id is not None:
        identity = session.get(Identity, body.identity_id)
        if identity is None:
            raise HTTPException(status_code=404, detail="identity not found")
        try:
            check_identity_consented(identity)
        except ComplianceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if identity.lora_uri:
            params["identity_lora_uri"] = identity.lora_uri

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=kind,
        prompt=prompt,
        params=params,
        fallback=[target.model_dump() for target in body.fallback],
        project_id=body.project_id,
        identity_id=body.identity_id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


# ---------------------------------------------------------------------------
# Advanced mode (M11): Uni3C custom trajectories + ReCamMaster re-shoot
# ---------------------------------------------------------------------------


class TrajectoryGenerateRequest(BaseModel):
    subject: str = Field(min_length=2)
    trajectory: list[TrajectoryPoint] = Field(max_length=MAX_TRAJECTORY_POINTS)
    image_uri: str  # Uni3C re-films a still — the source image is not optional
    provider: str = DEFAULT_PROVIDER
    model: str = UNI3C_MODEL
    fallback: list[GenerationTarget] = []
    project_id: uuid.UUID | None = None


class ReshootRequest(BaseModel):
    asset_id: uuid.UUID
    preset_ids: list[str] = Field(min_length=1, max_length=MAX_STACK)
    provider: str = DEFAULT_PROVIDER
    model: str = RECAM_MODEL
    project_id: uuid.UUID | None = None


@router.post("/trajectory", response_model=GenerationRead, status_code=201)
async def generate_from_trajectory(
    body: TrajectoryGenerateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        points = validate_trajectory(body.trajectory)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt, params = compose_trajectory(points, body.subject)
    params["image_uri"] = body.image_uri

    try:
        registry.resolve(body.provider, body.model, GenerationKind.image_to_video)
        for target in body.fallback:
            registry.resolve(target.provider, target.model, GenerationKind.image_to_video)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.image_to_video,
        prompt=prompt,
        params=params,
        fallback=[target.model_dump() for target in body.fallback],
        project_id=body.project_id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


@router.post("/reshoot", response_model=GenerationRead, status_code=201)
async def reshoot_asset(
    body: ReshootRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Re-shoot existing footage with a new camera move (ReCamMaster).
    Derives a NEW asset; the provenance chain records the source, exactly
    like the M13 effects lane."""
    try:
        presets = validate_stack(body.preset_ids)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt, params = compose_reshoot(presets)

    try:
        registry.resolve(body.provider, body.model, GenerationKind.video_to_video)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    source = session.get(Asset, body.asset_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source asset not found")

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.video_to_video,
        prompt=prompt,
        params={**params, "source_asset_uri": source.uri},
        project_id=body.project_id,
        source_asset_id=source.id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation
