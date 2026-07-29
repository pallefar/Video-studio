"""CPU stage functions consumed from the cpu queue."""

from __future__ import annotations

import uuid

import structlog

from pipeline_core.db import advance_job, fail_job, open_session
from pipeline_core.embeddings import get_embedder
from pipeline_core.stock import StockResult, download
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, JobStatus, RenderJob

log = structlog.get_logger()


def assemble_stage(job_id: str) -> None:
    from worker_cpu.ffmpeg.assemble import assemble

    with open_session() as session:
        job = session.get(RenderJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status != JobStatus.assemble:
            log.info("assemble_skip_idempotent", job_id=job_id, status=job.status.value)
            return
        try:
            assemble(ObjectStore(), job_id)
        except NotImplementedError:
            # M4 lands the ffmpeg chain; until then the job waits in assemble.
            log.info("assemble_pending_m4", job_id=job_id)
            return
        except Exception as exc:
            fail_job(session, job, f"assemble: {exc}")
            raise
        advance_job(session, job, JobStatus.review)


def generation_stage_api(generation_id: str) -> None:
    """API-provider generation: a network job. Deliberately no GPU lock —
    hosted models don't touch our card (asserted in tests/test_providers.py)."""
    from pipeline_core.generation import run_generation

    run_generation(generation_id)


def stock_ingest_stage(result: dict) -> str:
    """Download one stock search result into the object store and create the
    Asset row. The Asset only exists once its bytes are safely in MinIO.

    Structural rules (docs/psd.md §4.1): license and source_url are persisted
    always; has_identifiable_people defaults True until a human clears it;
    the asset starts unapproved.
    """
    stock = StockResult(**result)
    if not stock.license or not stock.source_url:
        raise ValueError("stock ingest requires license and source_url")

    store = ObjectStore()
    data = download(stock.download_url)
    extension = "mp4" if stock.kind == "video" else "jpg"
    key = f"assets/stock/{stock.provider}/{stock.external_id}.{extension}"
    uri = store.put_bytes(key, data)

    embedding = get_embedder().embed(stock.caption)
    with open_session() as session:
        asset = Asset(
            origin=AssetOrigin.stock,
            uri=uri,
            caption=stock.caption,
            duration_ms=stock.duration_ms,
            has_identifiable_people=True,
            license=stock.license,
            source_url=stock.source_url,
            approved=False,
            embedding=embedding,
        )
        session.add(asset)
        session.commit()
        asset_id = str(asset.id)
    log.info("stock_ingested", provider=stock.provider, external_id=stock.external_id, uri=uri)
    return asset_id
