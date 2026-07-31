from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.routes.assets import get_object_store
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.storage import ObjectStore
from pipeline_core.styles import format_spec
from schema.models import (
    Asset,
    Project,
    Shot,
    Storyboard,
    TimelineClip,
    TimelineDoc,
    TimelineDocCreate,
    TimelineDocRead,
    TimelineDocSave,
    TimelineDocument,
    utcnow,
)

router = APIRouter(tags=["timelines"])


def _get_or_404(session: Session, timeline_id: uuid.UUID) -> TimelineDoc:
    timeline = session.get(TimelineDoc, timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="timeline not found")
    return timeline


@router.post("/timelines", response_model=TimelineDocRead, status_code=201)
async def create_timeline(body: TimelineDocCreate, session: Session = Depends(get_session)):
    if body.project_id is not None and session.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    timeline = TimelineDoc(
        title=body.title,
        storyboard_id=body.storyboard_id,
        project_id=body.project_id,
        doc=body.doc,
    )
    session.add(timeline)
    session.commit()
    session.refresh(timeline)
    return timeline


@router.post("/storyboards/{storyboard_id}/edit", response_model=TimelineDocRead, status_code=201)
async def open_storyboard_in_editor(
    storyboard_id: uuid.UUID, session: Session = Depends(get_session)
):
    """Build an editable timeline from a storyboard: its shots laid out
    sequentially on the base video track."""
    board = session.get(Storyboard, storyboard_id)
    if board is None:
        raise HTTPException(status_code=404, detail="storyboard not found")
    shots = session.exec(
        select(Shot).where(Shot.storyboard_id == storyboard_id).order_by(Shot.idx)
    ).all()
    missing = [shot.idx for shot in shots if shot.asset_id is None]
    if missing:
        raise HTTPException(status_code=409, detail=f"shots without a finished asset: {missing}")

    clips = []
    cursor = 0
    for shot in shots:
        clips.append(
            TimelineClip(
                id=str(uuid.uuid4()),
                asset_id=str(shot.asset_id),
                start_ms=cursor,
                in_ms=0,
                out_ms=shot.duration_target_ms,
            )
        )
        cursor += shot.duration_target_ms

    timeline = TimelineDoc(
        title=board.title,
        storyboard_id=board.id,
        project_id=board.project_id,
        doc=TimelineDocument(format=board.format, video_tracks=[clips]),
    )
    session.add(timeline)
    session.commit()
    session.refresh(timeline)
    return timeline


@router.get("/timelines", response_model=list[TimelineDocRead])
async def list_timelines(
    session: Session = Depends(get_session), project_id: uuid.UUID | None = None
):
    stmt = select(TimelineDoc).order_by(TimelineDoc.created_at)
    if project_id is not None:
        stmt = stmt.where(TimelineDoc.project_id == project_id)
    return session.exec(stmt).all()


@router.get("/timelines/{timeline_id}", response_model=TimelineDocRead)
async def get_timeline(timeline_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_or_404(session, timeline_id)


@router.put("/timelines/{timeline_id}", response_model=TimelineDocRead)
async def save_timeline(
    timeline_id: uuid.UUID, body: TimelineDocSave, session: Session = Depends(get_session)
):
    """Optimistic concurrency: saving requires the version you loaded; a
    conflicting save gets a 409 and reloads."""
    timeline = _get_or_404(session, timeline_id)
    if body.base_version != timeline.version:
        raise HTTPException(
            status_code=409,
            detail=f"timeline changed (server v{timeline.version}, you had v{body.base_version}) — reload",
        )
    timeline.doc = body.doc
    timeline.version += 1
    timeline.updated_at = utcnow()
    session.add(timeline)
    session.commit()
    session.refresh(timeline)
    return timeline


@router.get("/timelines/{timeline_id}/media")
async def timeline_media(
    timeline_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    """Presigned playback URLs per asset so the editor previews without any
    further server round-trips. Prefers the 720p ingest proxy (M14) when one
    exists — cheaper decode, always browser-safe. Audio-track assets are
    included so the editor's transport can play music beds too."""
    timeline = _get_or_404(session, timeline_id)
    urls: dict[str, str] = {}
    clips = [
        clip
        for track in [*timeline.doc.video_tracks, *timeline.doc.audio_tracks]
        for clip in track
    ]
    for clip in clips:
        if clip.asset_id in urls:
            continue
        asset = session.get(Asset, uuid.UUID(clip.asset_id))
        if asset is None:
            continue
        proxy_key = f"assets/derived/{clip.asset_id}/proxy.mp4"
        if store.exists(proxy_key):
            urls[clip.asset_id] = store.presign_get(proxy_key)
            continue
        bucket, key = ObjectStore.parse_uri(asset.uri)
        if bucket == store.bucket:
            urls[clip.asset_id] = store.presign_get(key)
    return urls


@router.post("/timelines/{timeline_id}/export", status_code=202)
async def export_timeline(
    timeline_id: uuid.UUID,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Flatten the base video track into a render timeline (trims and text
    overlays included) and enqueue the cpu-lane render."""
    timeline = _get_or_404(session, timeline_id)
    doc = timeline.doc
    base_track = sorted(doc.video_tracks[0], key=lambda c: c.start_ms) if doc.video_tracks else []
    if not base_track:
        raise HTTPException(status_code=409, detail="timeline has no clips on the base track")

    spec = format_spec(doc.format)
    shots = []
    for index, clip in enumerate(base_track):
        asset = session.get(Asset, uuid.UUID(clip.asset_id))
        if asset is None:
            raise HTTPException(status_code=409, detail=f"clip {clip.id} references a missing asset")
        shots.append(
            {
                "idx": index,
                "asset_uri": asset.uri,
                "origin": asset.origin.value,
                "duration_ms": clip.out_ms - clip.in_ms,
                "in_ms": clip.in_ms,
                "subject": asset.caption or clip.id,
            }
        )

    total_ms = sum(shot["duration_ms"] for shot in shots)
    if spec["max_duration_s"] is not None and total_ms > spec["max_duration_s"] * 1000:
        raise HTTPException(
            status_code=409,
            detail=f"{doc.format.value} format is capped at {spec['max_duration_s']}s",
        )

    music = []
    for track in doc.audio_tracks:
        for clip in sorted(track, key=lambda c: c.start_ms):
            asset = session.get(Asset, uuid.UUID(clip.asset_id))
            if asset is None:
                raise HTTPException(
                    status_code=409, detail=f"audio clip {clip.id} references a missing asset"
                )
            music.append({**clip.model_dump(), "asset_uri": asset.uri})

    # Overlay track (video_tracks[1], M15 post-MVP): rendered as PiP by the
    # compiler. Origin rides along — a generated overlay forces C1 like a
    # generated shot.
    overlays = []
    for track in doc.video_tracks[1:2]:
        for clip in sorted(track, key=lambda c: c.start_ms):
            asset = session.get(Asset, uuid.UUID(clip.asset_id))
            if asset is None:
                raise HTTPException(
                    status_code=409, detail=f"overlay clip {clip.id} references a missing asset"
                )
            overlays.append(
                {**clip.model_dump(), "asset_uri": asset.uri, "origin": asset.origin.value}
            )

    render_timeline = {
        "storyboard_id": str(timeline.storyboard_id) if timeline.storyboard_id else str(timeline.id),
        "timeline_id": str(timeline.id),
        "project_id": str(timeline.project_id) if timeline.project_id else None,
        "title": timeline.title,
        "format": doc.format.value,
        "width": spec["width"],
        "height": spec["height"],
        "style": None,
        "transition_ms": doc.transition_ms,
        "shots": shots,
        "music": music,
        "overlays": overlays,
        "texts": [text.model_dump() for text in sorted(doc.texts, key=lambda t: t.start_ms)],
    }
    dispatcher.enqueue(
        QUEUE_CPU,
        "worker_cpu.stages.export_stage",
        str(timeline.id),
        render_timeline,
        job_key=f"export-timeline-{timeline.id}-v{timeline.version}",
    )
    return {"queued": f"export-timeline-{timeline.id}-v{timeline.version}", "timeline": render_timeline}
