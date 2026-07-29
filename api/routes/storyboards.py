from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.generation import enqueue_generation
from pipeline_core.presets import PresetError, compose, validate_stack
from pipeline_core.providers import ProviderRegistry, UnknownModelError
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.styles import STYLE_TEMPLATES, StyleError, format_spec, get_style
from schema.models import (
    Asset,
    Generation,
    GenerationKind,
    GenerationStatus,
    GenerationTarget,
    Project,
    Shot,
    ShotCreate,
    ShotRead,
    Storyboard,
    StoryboardCreate,
    StoryboardRead,
    StyleTemplateRead,
    VideoFormat,
    utcnow,
)

router = APIRouter(tags=["storyboards"])

DEFAULT_PROVIDER = "local"
DEFAULT_MODEL = "wan2.2-fun-camera"


@router.get("/styles", response_model=list[StyleTemplateRead])
async def list_styles():
    return STYLE_TEMPLATES


def _get_board(session: Session, storyboard_id: uuid.UUID) -> Storyboard:
    board = session.get(Storyboard, storyboard_id)
    if board is None:
        raise HTTPException(status_code=404, detail="storyboard not found")
    return board


def _shots(session: Session, storyboard_id: uuid.UUID) -> list[Shot]:
    return list(
        session.exec(
            select(Shot).where(Shot.storyboard_id == storyboard_id).order_by(Shot.idx)
        ).all()
    )


def _shot_read(session: Session, shot: Shot) -> ShotRead:
    """Resolve generation status and lazily propagate a succeeded generation's
    asset onto the shot."""
    status = None
    if shot.generation_id is not None:
        generation = session.get(Generation, shot.generation_id)
        if generation is not None:
            status = generation.status
            if status == GenerationStatus.succeeded and shot.asset_id is None:
                shot.asset_id = generation.asset_id
                session.add(shot)
                session.commit()
                session.refresh(shot)
    return ShotRead(**shot.model_dump(exclude={"preset_ids"}), preset_ids=list(shot.preset_ids or []), generation_status=status)


def _board_read(session: Session, board: Storyboard) -> StoryboardRead:
    session.refresh(board)  # commits in between expire the instance
    return StoryboardRead(
        **board.model_dump(),
        shots=[_shot_read(session, shot) for shot in _shots(session, board.id)],
    )


@router.post("/storyboards", response_model=StoryboardRead, status_code=201)
async def create_storyboard(body: StoryboardCreate, session: Session = Depends(get_session)):
    if body.style_id:
        try:
            get_style(body.style_id)
        except StyleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    board = Storyboard.model_validate(body)
    session.add(board)
    session.commit()
    session.refresh(board)
    return _board_read(session, board)


@router.get("/storyboards", response_model=list[StoryboardRead])
async def list_storyboards(
    session: Session = Depends(get_session), project_id: uuid.UUID | None = None
):
    stmt = select(Storyboard).order_by(Storyboard.created_at)
    if project_id is not None:
        stmt = stmt.where(Storyboard.project_id == project_id)
    boards = session.exec(stmt).all()
    return [_board_read(session, board) for board in boards]


@router.get("/storyboards/{storyboard_id}", response_model=StoryboardRead)
async def get_storyboard(storyboard_id: uuid.UUID, session: Session = Depends(get_session)):
    return _board_read(session, _get_board(session, storyboard_id))


@router.post("/storyboards/{storyboard_id}/shots", response_model=StoryboardRead, status_code=201)
async def add_shot(
    storyboard_id: uuid.UUID, body: ShotCreate, session: Session = Depends(get_session)
):
    board = _get_board(session, storyboard_id)
    if body.asset_id is not None:
        # An existing library/project asset serves as this shot directly.
        if session.get(Asset, body.asset_id) is None:
            raise HTTPException(status_code=404, detail="asset not found")
    if body.preset_ids or body.asset_id is None:
        try:
            validate_stack(body.preset_ids)
        except PresetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if any(shot.idx == body.idx for shot in _shots(session, storyboard_id)):
        raise HTTPException(status_code=409, detail=f"shot idx {body.idx} already exists")
    shot = Shot(**body.model_dump(exclude={"asset_id"}), storyboard_id=storyboard_id, asset_id=body.asset_id)
    session.add(shot)
    board.updated_at = utcnow()
    session.add(board)
    session.commit()
    return _board_read(session, board)


@router.delete("/storyboards/{storyboard_id}/shots/{shot_id}", response_model=StoryboardRead)
async def delete_shot(
    storyboard_id: uuid.UUID, shot_id: uuid.UUID, session: Session = Depends(get_session)
):
    board = _get_board(session, storyboard_id)
    shot = session.get(Shot, shot_id)
    if shot is None or shot.storyboard_id != storyboard_id:
        raise HTTPException(status_code=404, detail="shot not found")
    session.delete(shot)
    board.updated_at = utcnow()
    session.add(board)
    session.commit()
    return _board_read(session, board)


class ShotGenerateRequest(BaseModel):
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    fallback: list[GenerationTarget] = []


@router.post("/storyboards/{storyboard_id}/shots/{shot_id}/generate", response_model=StoryboardRead, status_code=201)
async def generate_shot(
    storyboard_id: uuid.UUID,
    shot_id: uuid.UUID,
    body: ShotGenerateRequest,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    board = _get_board(session, storyboard_id)
    shot = session.get(Shot, shot_id)
    if shot is None or shot.storyboard_id != storyboard_id:
        raise HTTPException(status_code=404, detail="shot not found")

    if not shot.preset_ids:
        raise HTTPException(status_code=422, detail="shot uses a fixed asset — nothing to generate")
    try:
        presets = validate_stack(list(shot.preset_ids))
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt, params = compose(presets, shot.subject)
    if board.style_id:
        style = get_style(board.style_id)
        prompt = f"{prompt}. {style.prompt_suffix}"
        params["style"] = style.id

    spec = format_spec(board.format)
    duration_s = shot.duration_target_ms / 1000
    if spec["max_duration_s"] is not None:
        duration_s = min(duration_s, spec["max_duration_s"])
    params.update(
        width=spec["width"], height=spec["height"], aspect=spec["aspect"], duration_s=duration_s
    )

    try:
        registry.resolve(body.provider, body.model, GenerationKind.text_to_video)
        for target in body.fallback:
            registry.resolve(target.provider, target.model, GenerationKind.text_to_video)
    except UnknownModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    generation = Generation(
        provider=body.provider,
        model=body.model,
        kind=GenerationKind.text_to_video,
        prompt=prompt,
        params=params,
        fallback=[target.model_dump() for target in body.fallback],
        project_id=board.project_id,
    )
    session.add(generation)
    session.commit()
    session.refresh(generation)

    shot.generation_id = generation.id
    shot.asset_id = None  # regenerating replaces the previous take
    board.updated_at = utcnow()
    session.add(shot)
    session.add(board)
    session.commit()
    enqueue_generation(dispatcher, generation, registry)
    return _board_read(session, board)


@router.post("/storyboards/{storyboard_id}/export", status_code=202)
async def export_storyboard(
    storyboard_id: uuid.UUID,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Compile the storyboard into a timeline document and enqueue the
    full-length render on the cpu lane. The ffmpeg compiler is M16; until it
    lands the export job waits, exactly like assemble."""
    board = _get_board(session, storyboard_id)
    reads = [_shot_read(session, shot) for shot in _shots(session, storyboard_id)]
    if not reads:
        raise HTTPException(status_code=409, detail="storyboard has no shots")

    missing = [read.idx for read in reads if read.asset_id is None]
    if missing:
        raise HTTPException(
            status_code=409, detail=f"shots without a finished asset: {missing}"
        )

    spec = format_spec(board.format)
    total_ms = sum(read.duration_target_ms for read in reads)
    if spec["max_duration_s"] is not None and total_ms > spec["max_duration_s"] * 1000:
        raise HTTPException(
            status_code=409,
            detail=f"{board.format.value} format is capped at {spec['max_duration_s']}s, "
            f"storyboard totals {total_ms / 1000:.0f}s",
        )

    assets = {read.asset_id: session.get(Asset, read.asset_id) for read in reads}
    timeline = {
        "storyboard_id": str(board.id),
        "title": board.title,
        "format": board.format.value,
        "width": spec["width"],
        "height": spec["height"],
        "style": board.style_id,
        "shots": [
            {
                "idx": read.idx,
                "asset_uri": assets[read.asset_id].uri,
                "duration_ms": read.duration_target_ms,
                "subject": read.subject,
            }
            for read in reads
        ],
    }
    dispatcher.enqueue(
        QUEUE_CPU,
        "worker_cpu.stages.export_stage",
        str(board.id),
        timeline,
        job_key=f"export-{board.id}",
    )
    return {"queued": f"export-{board.id}", "timeline": timeline}
