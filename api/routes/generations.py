from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import get_dispatcher
from api.validators.compliance import ComplianceError, check_identity_consented
from pipeline_core.dispatch import Dispatcher
from pipeline_core.generation import enqueue_generation
from pipeline_core.providers import ProviderRegistry, UnknownModelError, build_registry
from schema.models import Generation, GenerationCreate, GenerationRead, Identity

router = APIRouter(prefix="/generations", tags=["generations"])

_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


class CatalogEntry(BaseModel):
    provider: str
    model: str
    kinds: list[str]
    provider_class: str
    notes: str = ""


@router.get("/catalog", response_model=list[CatalogEntry])
async def catalog(registry: ProviderRegistry = Depends(get_registry)):
    return [
        CatalogEntry(
            provider=spec.provider,
            model=spec.model,
            kinds=sorted(k.value for k in spec.kinds),
            provider_class=spec.provider_class,
            notes=spec.notes,
        )
        for spec in registry.catalog()
    ]


@router.post("", response_model=GenerationRead, status_code=201)
async def create_generation(
    body: GenerationCreate,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        registry.resolve(body.provider, body.model, body.kind)
        for target in body.fallback:
            registry.resolve(target.provider, target.model, body.kind)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt = body.prompt
    params = body.params
    if body.enhance:
        from pipeline_core.enhance import apply_enhancement

        prompt, params = apply_enhancement(prompt, params)

    if body.identity_id is not None:
        identity = session.get(Identity, body.identity_id)
        if identity is None:
            raise HTTPException(status_code=404, detail="identity not found")
        try:
            check_identity_consented(identity)
        except ComplianceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if identity.lora_uri:
            params = {**(params or {}), "identity_lora_uri": identity.lora_uri}

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=body.kind,
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


@router.get("", response_model=list[GenerationRead])
async def list_generations(session: Session = Depends(get_session)):
    return session.exec(select(Generation).order_by(Generation.created_at)).all()


@router.get("/{generation_id}", response_model=GenerationRead)
async def get_generation(generation_id: uuid.UUID, session: Session = Depends(get_session)):
    generation = session.get(Generation, generation_id)
    if generation is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return generation
