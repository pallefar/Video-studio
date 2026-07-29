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


def _find_ffmpeg() -> str | None:
    import shutil

    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def export_stage(storyboard_id: str, timeline: dict) -> str | None:
    """Full-length export (M16): timeline document -> ffmpeg render -> asset.

    The timeline carries format (long 16:9 / short 9:16), style, and ordered
    shot uris with origins. The watermark decision lives inside the compiler
    (C1 — no off-switch); the rendered export lands back in the library, and
    in the storyboard's project pool, as an asset of its own.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    from worker_cpu.ffmpeg.compiler import build_ffmpeg_args, watermark_required
    from worker_cpu.ffmpeg.overlay import make_watermark_png

    binary = _find_ffmpeg()
    if binary is None:
        log.warning("export_waiting_for_ffmpeg", storyboard_id=storyboard_id)
        return None

    store = ObjectStore()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shot_paths = []
        for shot in timeline["shots"]:
            _, key = store.parse_uri(shot["asset_uri"])
            local = tmp_path / f"shot_{shot['idx']}.mp4"
            store.get_file(key, local)
            shot_paths.append(str(local))

        overlay = None
        if watermark_required(timeline):
            overlay = str(
                make_watermark_png(tmp_path / "watermark.png", timeline["width"], timeline["height"])
            )

        output = tmp_path / "render.mp4"
        args = build_ffmpeg_args(timeline, shot_paths, str(output), overlay, ffmpeg_bin=binary)
        result = subprocess.run(args, capture_output=True)
        if result.returncode != 0:
            tail = result.stderr.decode(errors="replace")[-800:]
            raise RuntimeError(f"ffmpeg export failed for {storyboard_id}: {tail}")
        uri = store.put_file(f"renders/{storyboard_id}/final.mp4", output)

    from schema.models import ProjectAsset, Storyboard

    with open_session() as session:
        asset = Asset(
            origin=AssetOrigin.generated if overlay else AssetOrigin.own,
            uri=uri,
            caption=f"Export - {timeline.get('title', storyboard_id)}",
            duration_ms=sum(s["duration_ms"] for s in timeline["shots"]),
            has_identifiable_people=False,
            approved=False,
            embedding=get_embedder().embed(str(timeline.get("title", ""))),
        )
        session.add(asset)
        session.commit()
        board = session.get(Storyboard, uuid.UUID(storyboard_id))
        if board is not None and board.project_id is not None:
            session.add(ProjectAsset(project_id=board.project_id, asset_id=asset.id))
            session.commit()
    log.info("export_done", storyboard_id=storyboard_id, uri=uri, watermarked=bool(overlay))
    return uri


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
