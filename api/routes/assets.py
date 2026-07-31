from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.routes.jobs import get_dispatcher
from pipeline_core.dispatch import Dispatcher
from pipeline_core.embeddings import Embedder, get_embedder
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.resolver import DEFAULT_THRESHOLD, resolve_asset
from pipeline_core.stock import StockKind, StockResult, get_providers
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetCreate, AssetOrigin, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


def get_object_store() -> ObjectStore:
    return ObjectStore()


def get_stock_providers() -> list:
    return get_providers()


_embedder: Embedder | None = None


def get_embedder_dep() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = get_embedder()
    return _embedder


class StockSearchResult(BaseModel):
    provider: str
    external_id: str
    kind: StockKind
    caption: str
    download_url: str
    preview_url: str
    source_url: str
    license: str
    duration_ms: int | None = None


def _get_or_404(session: Session, asset_id: uuid.UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@router.post("", response_model=AssetRead, status_code=201)
async def create_asset(body: AssetCreate, session: Session = Depends(get_session)):
    asset = Asset.model_validate(body)
    # embed at creation like every other ingest path — an asset without an
    # embedding is invisible to the resolver's cosine search
    if body.caption:
        asset.embedding = get_embedder_dep().embed(body.caption)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("", response_model=list[AssetRead])
async def list_assets(session: Session = Depends(get_session)):
    return session.exec(select(Asset).order_by(Asset.created_at)).all()


@router.post("/upload", response_model=AssetRead, status_code=201)
async def upload_asset(
    file: UploadFile,
    caption: str | None = Form(default=None),
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    """Bring your own media — footage, music beds, images. Uploads are the
    owner's material: origin='own', approved, no identifiable-people hold."""
    import mimetypes
    from pathlib import PurePosixPath

    suffix = PurePosixPath(file.filename or "upload.bin").suffix or ".bin"
    key = f"assets/uploads/{uuid.uuid4()}{suffix}"
    content_type = file.content_type or mimetypes.guess_type(key)[0]
    data = await file.read()
    uri = store.put_bytes(key, data, content_type=content_type)

    text = caption or (file.filename or "upload")
    asset = Asset(
        origin=AssetOrigin.own,
        uri=uri,
        caption=text,
        has_identifiable_people=False,
        approved=True,
        embedding=get_embedder_dep().embed(text),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("/resolve", response_model=AssetRead)
async def resolve(
    query: str = Query(min_length=2),
    threshold: float = DEFAULT_THRESHOLD,
    session: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder_dep),
):
    """Tier-1 resolution. 404 means: fall through to stock search (tier 2) or
    the generative lane (tier 3). Flagged/unapproved assets are never returned."""
    asset = resolve_asset(session, query, embedder, threshold)
    if asset is None:
        raise HTTPException(status_code=404, detail="no approved asset above threshold")
    return asset


_IMAGE_SUFFIXES = ("png", "jpg", "jpeg", "webp")


@router.get("/thumbs")
async def asset_thumbs(
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    """asset_id -> presigned thumbnail URL. Preference order: the M14 poster
    frame, then the scrub sprite (older ingests), then the asset itself when
    it is an image. Video assets without derivatives simply have no thumb —
    the panel shows a placeholder. One store listing plus a column-only
    select — never full Asset hydration (rows carry embedding vectors)."""
    posters: dict[str, str] = {}
    sprites: dict[str, str] = {}
    for key in store.list_keys("assets/derived/"):
        parts = key.split("/")
        if len(parts) != 4:
            continue
        if parts[3] == "poster.jpg":
            posters[parts[2]] = key
        elif parts[3] == "sprite.jpg":
            sprites[parts[2]] = key

    thumbs: dict[str, str] = {}
    for asset_id, uri in session.exec(select(Asset.id, Asset.uri)).all():
        key_id = str(asset_id)
        if key_id in posters:
            thumbs[key_id] = store.presign_get(posters[key_id])
        elif key_id in sprites:
            thumbs[key_id] = store.presign_get(sprites[key_id])
        elif uri.rsplit(".", 1)[-1].lower() in _IMAGE_SUFFIXES:
            try:
                bucket, key = store.parse_uri(uri)
            except ValueError:
                continue
            if bucket != store.bucket:
                # same guard download_asset enforces — never sign for a key
                # the uri doesn't actually point at
                continue
            thumbs[key_id] = store.presign_get(key)
    return thumbs


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_or_404(session, asset_id)


@router.get("/{asset_id}/download")
async def download_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    """Presigned download URL — for posting an asset straight to social media
    or pulling it into another tool. Assets stand alone, not just in videos."""
    asset = _get_or_404(session, asset_id)
    try:
        bucket, key = ObjectStore.parse_uri(asset.uri)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"asset has no downloadable uri: {exc}") from exc
    if bucket != store.bucket:
        raise HTTPException(status_code=409, detail="asset lives outside the configured bucket")
    return {"url": store.presign_get(key), "uri": asset.uri}


@router.get("/stock/search", response_model=list[StockSearchResult])
async def stock_search(
    query: str = Query(min_length=2),
    kind: StockKind = "video",
    providers: list = Depends(get_stock_providers),
):
    if not providers:
        raise HTTPException(
            status_code=503,
            detail="no stock providers configured — set PEXELS_API_KEY / PIXABAY_API_KEY",
        )
    results: list[StockSearchResult] = []
    for provider in providers:
        results.extend(StockSearchResult(**asdict(r)) for r in provider.search(query, kind))
    return results


@router.post("/stock/ingest", status_code=202)
async def stock_ingest(
    body: StockSearchResult,
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Enqueue the download onto the cpu lane; the Asset row appears once the
    bytes are in MinIO (see worker_cpu.stages.stock_ingest_stage)."""
    if not body.license or not body.source_url:
        raise HTTPException(status_code=422, detail="stock ingest requires license and source_url")
    job_key = f"stock-ingest-{body.provider}-{body.external_id}"
    dispatcher.enqueue(
        QUEUE_CPU, "worker_cpu.stages.stock_ingest_stage", body.model_dump(), job_key=job_key
    )
    return {"queued": job_key}


@router.post("/{asset_id}/approve", response_model=AssetRead)
async def approve_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    """Human approval gate: clears the identifiable-people flag hold and makes
    the asset selectable by the resolver (M8)."""
    asset = _get_or_404(session, asset_id)
    asset.approved = True
    asset.has_identifiable_people = False
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/{asset_id}/flag", response_model=AssetRead)
async def flag_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    asset = _get_or_404(session, asset_id)
    asset.approved = False
    asset.has_identifiable_people = True
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/{asset_id}/ingest", status_code=202)
async def ingest_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
    dispatcher=Depends(get_dispatcher),
):
    """Queue derivative production (720p proxy, scrub sprites + VTT, waveform
    peaks) on the cpu lane. Idempotent — existing derivatives are kept."""
    _get_or_404(session, asset_id)
    job_key = f"ingest-{asset_id}"
    dispatcher.enqueue(QUEUE_CPU, "worker_cpu.stages.ingest_stage", str(asset_id), job_key=job_key)
    return {"queued": job_key}


@router.get("/{asset_id}/derived")
async def derived_media(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    """Presigned URLs for whichever editor derivatives exist."""
    _get_or_404(session, asset_id)
    prefix = f"assets/derived/{asset_id}"
    urls = {}
    for name, key in [
        ("proxy", f"{prefix}/proxy.mp4"),
        ("poster", f"{prefix}/poster.jpg"),
        ("sprite", f"{prefix}/sprite.jpg"),
        ("vtt", f"{prefix}/sprite.vtt"),
        ("peaks", f"{prefix}/peaks.json"),
    ]:
        if store.exists(key):
            urls[name] = store.presign_get(key)
    return urls


@router.get("/{asset_id}/provenance")
async def asset_provenance(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    """Walk the derivation chain (M13): each hop is an asset plus the
    generation that produced it (null for stock/own roots). Ordered from the
    requested asset back to the original source."""
    from schema.models import Generation

    _get_or_404(session, asset_id)
    chain = []
    current: uuid.UUID | None = asset_id
    for _ in range(10):  # derivation chains are short; cap defends against cycles
        if current is None:
            break
        asset = session.get(Asset, current)
        if asset is None:
            break
        generation = session.exec(
            select(Generation).where(Generation.asset_id == current)
        ).first()
        chain.append(
            {
                "asset": AssetRead.model_validate(asset).model_dump(mode="json"),
                "generation": None
                if generation is None
                else {
                    "id": str(generation.id),
                    "provider": generation.provider,
                    "model": generation.model,
                    "kind": generation.kind.value,
                    "prompt": generation.prompt,
                    "params": generation.params,
                    "source_asset_id": str(generation.source_asset_id)
                    if generation.source_asset_id
                    else None,
                },
            }
        )
        current = generation.source_asset_id if generation is not None else None
    return chain
