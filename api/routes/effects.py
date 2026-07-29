"""VFX & finishing lane (M13) — effect presets over VACE v2v, stackable with
camera presets (Higgsfield 'Mix'), plus the upscale/interpolate finishing
pass. Every application derives a NEW asset; the source is never touched.
Provenance chain: derived asset -> generation (provider/model/params,
source_asset_id) -> source asset, walkable via GET /assets/{id}/provenance.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.effects import (
    EFFECT_PRESETS,
    MAX_EFFECT_STACK,
    VACE_FULL,
    VACE_PREVIEW,
    EffectError,
    compose_mix,
)
from pipeline_core.generation import enqueue_generation
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from schema.models import (
    Asset,
    EffectPresetRead,
    Generation,
    GenerationKind,
    GenerationRead,
    Project,
)

router = APIRouter(prefix="/effects", tags=["effects"])

DEFAULT_PROVIDER = "local"
DEFAULT_UPSCALE_MODEL = "seedvr2-3b"


class EffectApplyRequest(BaseModel):
    asset_id: uuid.UUID
    effect_ids: list[str] = Field(min_length=1, max_length=MAX_EFFECT_STACK)
    camera_preset_ids: list[str] = []  # the 'Mix' mechanic
    preview: bool = False  # fast path on VACE 1.3B
    provider: str = DEFAULT_PROVIDER
    model: str | None = None  # default picked by preview flag
    project_id: uuid.UUID | None = None


class UpscaleRequest(BaseModel):
    asset_id: uuid.UUID
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_UPSCALE_MODEL
    project_id: uuid.UUID | None = None


def _source_or_404(session: Session, asset_id: uuid.UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="source asset not found")
    return asset


def _checked_project(session: Session, project_id: uuid.UUID | None) -> None:
    if project_id is not None and session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")


def _spawn_derived(
    session: Session,
    dispatcher: Dispatcher,
    registry: ProviderRegistry,
    *,
    provider: str,
    model: str,
    kind: GenerationKind,
    prompt: str,
    params: dict,
    source: Asset,
    project_id: uuid.UUID | None,
) -> Generation:
    generation = Generation(
        provider=provider,
        model=model,
        kind=kind,
        prompt=prompt,
        params={**params, "source_asset_uri": source.uri},
        project_id=project_id,
        source_asset_id=source.id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


@router.get("", response_model=list[EffectPresetRead])
async def list_effects():
    return EFFECT_PRESETS


@router.post("/apply", response_model=GenerationRead, status_code=201)
async def apply_effects(
    body: EffectApplyRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        prompt, params = compose_mix(body.effect_ids, body.camera_preset_ids)
    except EffectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    model = body.model or (VACE_PREVIEW if body.preview else VACE_FULL)
    try:
        registry.resolve(body.provider, model, GenerationKind.video_to_video)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)
    source = _source_or_404(session, body.asset_id)

    return _spawn_derived(
        session, dispatcher, registry,
        provider=body.provider, model=model, kind=GenerationKind.video_to_video,
        prompt=prompt, params={**params, "preview": body.preview},
        source=source, project_id=body.project_id,
    )


@router.post("/upscale", response_model=GenerationRead, status_code=201)
async def upscale_asset(
    body: UpscaleRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Finishing pass: SeedVR2 for hero shots, Real-ESRGAN cheap lane, FILM
    for interpolation — all kind=upscale over the same derived-asset flow."""
    try:
        registry.resolve(body.provider, body.model, GenerationKind.upscale)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)
    source = _source_or_404(session, body.asset_id)

    return _spawn_derived(
        session, dispatcher, registry,
        provider=body.provider, model=body.model, kind=GenerationKind.upscale,
        prompt=f"finishing pass ({body.model}) on {source.caption or source.uri}",
        params={"purpose": "finishing"},
        source=source, project_id=body.project_id,
    )
