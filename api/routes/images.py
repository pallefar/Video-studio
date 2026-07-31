"""Image studio (M12) — the "Soul" equivalent, through the provider layer.

Three flows, all landing as Assets with origin='generated' like every other
generation:
- single image: style preset + prompt -> one generation
- storyboard mode ("Popcorn"): N frames sharing one seed + style, so a
  sequence holds together; the shared params are recorded on every frame
- thumbnail pipeline: the YouTube flow — 1280x720 on the text-capable model

Identity use passes the same C6 consent gate as every face-bearing path.
"""

from __future__ import annotations

import secrets
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
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from pipeline_core.styles import StyleError, get_style
from schema.models import (
    Generation,
    GenerationKind,
    GenerationRead,
    Identity,
    Project,
)

router = APIRouter(prefix="/images", tags=["images"])

SEED_MAX = 2**31 - 1
MAX_FRAMES = 9

DEFAULT_PROVIDER = "local"
DEFAULT_MODEL = "z-image-turbo"
THUMBNAIL_MODEL = "qwen-image"  # text-heavy: titles must render legibly
THUMBNAIL_SIZE = (1280, 720)  # YouTube's thumbnail resolution


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=2)
    style_id: str | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    # Storyboard mode: frames > 1 renders a sequence sharing seed + style.
    frames: int = Field(default=1, ge=1, le=MAX_FRAMES)
    seed: int | None = Field(default=None, ge=0, le=SEED_MAX)
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)
    project_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None


class ThumbnailRequest(BaseModel):
    title: str = Field(min_length=2)
    style_id: str | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = THUMBNAIL_MODEL
    seed: int | None = Field(default=None, ge=0, le=SEED_MAX)
    project_id: uuid.UUID | None = None


def _gated_identity(session: Session, identity_id: uuid.UUID | None) -> Identity | None:
    if identity_id is None:
        return None
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="identity not found")
    try:
        check_identity_consented(identity)
    except ComplianceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return identity


def _checked_project(session: Session, project_id: uuid.UUID | None) -> None:
    if project_id is not None and session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")


def _styled_prompt(prompt: str, style_id: str | None) -> tuple[str, str | None]:
    if style_id is None:
        return prompt, None
    try:
        style = get_style(style_id)
    except StyleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return f"{prompt}, {style.prompt_suffix}", style.id


def _spawn(
    session: Session,
    dispatcher: Dispatcher,
    registry: ProviderRegistry,
    *,
    provider: str,
    model: str,
    prompt: str,
    params: dict,
    project_id: uuid.UUID | None,
    identity: Identity | None,
) -> Generation:
    if identity is not None and identity.lora_uri:
        params = {**params, "identity_lora_uri": identity.lora_uri}
    generation = Generation(
        provider=provider,
        model=model,
        kind=GenerationKind.image,
        prompt=prompt,
        params=params,
        project_id=project_id,
        identity_id=identity.id if identity is not None else None,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


@router.post("/generate", response_model=list[GenerationRead], status_code=201)
async def generate_images(
    body: ImageGenerateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    try:
        registry.resolve(body.provider, body.model, GenerationKind.image)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)
    identity = _gated_identity(session, body.identity_id)
    prompt, style_id = _styled_prompt(body.prompt, body.style_id)

    # One seed for the whole request: storyboard frames must hold together.
    seed = body.seed if body.seed is not None else secrets.randbelow(SEED_MAX)
    shared = {
        "seed": seed,
        "style": style_id,
        "width": body.width,
        "height": body.height,
        "frames": body.frames,
    }
    return [
        _spawn(
            session, dispatcher, registry,
            provider=body.provider, model=body.model, prompt=prompt,
            params={**shared, "frame": frame},
            project_id=body.project_id, identity=identity,
        )
        for frame in range(body.frames)
    ]


@router.post("/thumbnail", response_model=GenerationRead, status_code=201)
async def generate_thumbnail(
    body: ThumbnailRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """The YouTube flow: a 1280x720 thumbnail whose title text must survive —
    routed to the text-capable model by default."""
    try:
        registry.resolve(body.provider, body.model, GenerationKind.image)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)
    prompt, style_id = _styled_prompt(
        f'YouTube thumbnail, bold large readable title text "{body.title}", '
        "high contrast focal subject, uncluttered composition",
        body.style_id,
    )
    width, height = THUMBNAIL_SIZE
    seed = body.seed if body.seed is not None else secrets.randbelow(SEED_MAX)
    return _spawn(
        session, dispatcher, registry,
        provider=body.provider, model=body.model, prompt=prompt,
        params={
            "seed": seed, "style": style_id, "width": width, "height": height,
            "purpose": "thumbnail",
        },
        project_id=body.project_id, identity=None,
    )


# --- M28: image -> motion --------------------------------------------------


class AnimateRequest(BaseModel):
    """Animate a still from the library — the cheap-b-roll path: generate
    once as an image, bring it to life only when a video is worth the lane
    time (or the API dollars)."""

    asset_id: uuid.UUID
    prompt: str | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = "wan2.2-i2v"
    duration_s: int = Field(default=5, ge=1, le=15)
    project_id: uuid.UUID | None = None


class TalkRequest(BaseModel):
    """Talking / singing photo. Face-bearing generation — a consented
    Identity is REQUIRED (C6), not optional. Provide a script (spoken via
    the identity's voice profile) OR an audio asset (a song vocal makes it
    a singing photo)."""

    asset_id: uuid.UUID
    identity_id: uuid.UUID
    script: str | None = Field(default=None, max_length=2000)
    audio_asset_id: uuid.UUID | None = None
    voice_profile_id: uuid.UUID | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = "musetalk-image"
    project_id: uuid.UUID | None = None


def _image_asset_or_422(session: Session, asset_id: uuid.UUID):
    from schema.models import Asset

    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    if asset.uri.rsplit(".", 1)[-1].lower() not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(status_code=422, detail="asset is not an image")
    return asset


@router.post("/animate", response_model=GenerationRead, status_code=201)
async def animate_image(
    body: AnimateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    asset = _image_asset_or_422(session, body.asset_id)
    try:
        registry.resolve(body.provider, body.model, GenerationKind.image_to_video)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.image_to_video,
        prompt=body.prompt or (asset.caption or "bring this image to life, subtle natural motion"),
        params={
            "source_asset_uri": asset.uri,
            "duration_s": body.duration_s,
        },
        project_id=body.project_id,
        source_asset_id=asset.id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation


@router.post("/talk", response_model=GenerationRead, status_code=201)
async def talk_image(
    body: TalkRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    from schema.models import Asset, VoiceProfile

    asset = _image_asset_or_422(session, body.asset_id)
    if bool(body.script) == bool(body.audio_asset_id):
        raise HTTPException(
            status_code=422,
            detail="provide exactly one of script (talking) or audio_asset_id (singing)",
        )
    try:
        registry.resolve(body.provider, body.model, GenerationKind.talking_image)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _checked_project(session, body.project_id)

    # C6: talking photos are face-bearing by definition — consent is not
    # optional here, unlike stills where an identity merely styles the output.
    identity = _gated_identity(session, body.identity_id)
    assert identity is not None  # identity_id is required by the schema

    params: dict = {"source_asset_uri": asset.uri}
    if body.script:
        params["script"] = body.script
        if body.voice_profile_id is not None:
            if session.get(VoiceProfile, body.voice_profile_id) is None:
                raise HTTPException(status_code=404, detail="voice profile not found")
            params["voice_profile_id"] = str(body.voice_profile_id)
    else:
        audio = session.get(Asset, body.audio_asset_id)
        if audio is None:
            raise HTTPException(status_code=404, detail="audio asset not found")
        params["audio_asset_uri"] = audio.uri

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.talking_image,
        prompt=body.script or f"singing photo of {asset.caption or 'the subject'}",
        params=params,
        project_id=body.project_id,
        identity_id=identity.id,
        source_asset_id=asset.id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)
    enqueue_generation(dispatcher, generation, registry)
    return generation
