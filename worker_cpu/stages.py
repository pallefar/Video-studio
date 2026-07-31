"""CPU stage functions consumed from the cpu queue."""

from __future__ import annotations

import uuid

import structlog

from pipeline_core.db import advance_job, fail_job, open_session
from pipeline_core.metrics import timed_stage
from pipeline_core.embeddings import get_embedder
from pipeline_core.stock import StockResult, download
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, JobStatus, RenderJob

log = structlog.get_logger()


@timed_stage("assemble")
def assemble_stage(job_id: str) -> None:
    """M4: voice bus + loudnorm + chunk concat + b-roll + captions + C1
    watermark + encode. Progress streams into the metrics table like the
    M16 exports; the assembled uri lands on the job for the M7 preview."""
    from sqlmodel import select

    from pipeline_core.resolver import resolve_asset
    from worker_cpu.ffmpeg.assemble import BROLL_MAX_MS, assemble
    from schema.models import Segment, utcnow

    binary = _find_ffmpeg()
    if binary is None:
        log.warning("assemble_waiting_for_ffmpeg", job_id=job_id)
        return

    with open_session() as session:
        job = session.get(RenderJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status != JobStatus.assemble:
            log.info("assemble_skip_idempotent", job_id=job_id, status=job.status.value)
            return

        rows = session.exec(
            select(Segment).where(Segment.job_id == job.id).order_by(Segment.idx)
        ).all()
        segments = [
            {
                "idx": s.idx, "text": s.text, "audio_uri": s.audio_uri,
                "duration_ms": s.duration_ms, "pause_after_ms": s.pause_after_ms,
            }
            for s in rows
        ]

        # B-roll beats: one cutaway per resolvable segment, inserted at the
        # segment's start; the resolver never returns flagged/unapproved assets.
        broll = []
        embedder = get_embedder()
        clock_ms = 0
        for segment in segments:
            duration_ms = segment["duration_ms"] or 0
            asset = resolve_asset(session, segment["text"], embedder)
            if asset is not None and asset.duration_ms:
                span = min(BROLL_MAX_MS, duration_ms, asset.duration_ms)
                if span > 0:
                    broll.append(
                        {"uri": asset.uri, "start_ms": clock_ms, "end_ms": clock_ms + span}
                    )
            clock_ms += duration_ms + segment["pause_after_ms"]

        total_ms = clock_ms
        recorder = _ProgressRecorder(job_id, total_ms)
        recorder.start()
        try:
            uri = assemble(
                ObjectStore(), job_id, segments, broll=broll,
                ffmpeg_bin=binary, on_progress=recorder,
            )
        except Exception as exc:
            fail_job(session, job, f"assemble: {exc}")
            raise
        recorder.finish()
        job.output_uri = uri
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
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


EXPORT_PROGRESS_STAGE = "export_progress"
EXPORT_TOTAL_STAGE = "export_total"
_PROGRESS_STEP_PCT = 10


def _record_progress_metric(stage: str, ref: str, value_ms: int) -> None:
    """Progress snapshots live in the metrics table like every stage duration.
    Recording must never take the render down — failures are swallowed."""
    try:
        from schema.models import Metric

        with open_session() as session:
            session.add(Metric(stage=stage, ref=ref, duration_ms=value_ms))
            session.commit()
    except Exception as exc:
        log.warning("progress_metric_write_failed", stage=stage, ref=ref, error=str(exc))


class _ProgressRecorder:
    """Throttles -progress callbacks to >=10% steps so a long render writes
    ~10 rows, not one per ffmpeg status block."""

    def __init__(self, ref: str, total_ms: int):
        self.ref = ref
        self.total_ms = max(1, total_ms)
        self._last_recorded_ms = 0

    def __call__(self, position_ms: int) -> None:
        step_ms = self.total_ms * _PROGRESS_STEP_PCT // 100
        if position_ms - self._last_recorded_ms < max(1, step_ms):
            return
        self._last_recorded_ms = position_ms
        _record_progress_metric(EXPORT_PROGRESS_STAGE, self.ref, min(position_ms, self.total_ms))

    def start(self) -> None:
        _record_progress_metric(EXPORT_TOTAL_STAGE, self.ref, self.total_ms)

    def finish(self) -> None:
        _record_progress_metric(EXPORT_PROGRESS_STAGE, self.ref, self.total_ms)


@timed_stage("export")
def export_stage(storyboard_id: str, timeline: dict) -> str | None:
    """Full-length export (M16): timeline document -> ffmpeg render -> asset.

    The timeline carries format (long 16:9 / short 9:16), style, and ordered
    shot uris with origins. The watermark decision lives inside the compiler
    (C1 — no off-switch); the rendered export lands back in the library, and
    in the storyboard's project pool, as an asset of its own. Render position
    is parsed from ffmpeg -progress into the metrics table live.
    """
    import tempfile
    from pathlib import Path

    from worker_cpu.ffmpeg.compiler import build_ffmpeg_args, expected_duration_ms, watermark_required
    from worker_cpu.ffmpeg.overlay import make_text_png, make_watermark_png
    from worker_cpu.ffmpeg.progress import run_ffmpeg_with_progress

    binary = _find_ffmpeg()
    if binary is None:
        log.warning("export_waiting_for_ffmpeg", storyboard_id=storyboard_id)
        return None

    from worker_cpu.ffmpeg.ingest import probe

    store = ObjectStore()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shot_paths = []
        for shot in timeline["shots"]:
            _, key = store.parse_uri(shot["asset_uri"])
            local = tmp_path / f"shot_{shot['idx']}.mp4"
            store.get_file(key, local)
            shot_paths.append(str(local))
            # the voice bus needs to know which shots actually carry audio
            shot["has_audio"] = bool(probe(binary, local)["has_audio"])

        music_paths = []
        for n, clip in enumerate(timeline.get("music", [])):
            _, key = store.parse_uri(clip["asset_uri"])
            local = tmp_path / f"music_{n}"
            store.get_file(key, local)
            music_paths.append(str(local))

        overlay_paths = []
        for n, clip in enumerate(timeline.get("overlays", [])):
            _, key = store.parse_uri(clip["asset_uri"])
            local = tmp_path / f"overlay_{n}.mp4"
            store.get_file(key, local)
            overlay_paths.append(str(local))

        overlay = None
        if watermark_required(timeline):
            overlay = str(
                make_watermark_png(tmp_path / "watermark.png", timeline["width"], timeline["height"])
            )

        text_pngs = [
            str(make_text_png(tmp_path / f"text_{n}.png", text["text"], timeline["height"], scale=18))
            for n, text in enumerate(timeline.get("texts", []))
        ]

        output = tmp_path / "render.mp4"
        args = build_ffmpeg_args(
            timeline, shot_paths, str(output), overlay,
            text_pngs=text_pngs, music_paths=music_paths,
            overlay_paths=overlay_paths, ffmpeg_bin=binary,
        )
        recorder = _ProgressRecorder(storyboard_id, expected_duration_ms(timeline))
        recorder.start()
        run_ffmpeg_with_progress(
            args, on_progress=recorder, label=f"ffmpeg export {storyboard_id}"
        )
        recorder.finish()
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
        project_id = timeline.get("project_id")
        if project_id is None:
            board = session.get(Storyboard, uuid.UUID(storyboard_id))
            if board is not None:
                project_id = board.project_id
        if project_id is not None:
            session.add(ProjectAsset(project_id=uuid.UUID(str(project_id)), asset_id=asset.id))
            session.commit()
    log.info("export_done", storyboard_id=storyboard_id, uri=uri, watermarked=bool(overlay))
    return uri


@timed_stage("loop_preprocess")
def loop_preprocess_stage(loop_id: str) -> None:
    """M2 (CPU half): reject VFR at ingest, score the loop seam, and switch
    to ping-pong playback when the boundary pops. The MuseTalk latent cache
    is the GPU half (worker_gpu/preprocess), built on the workstation."""
    import tempfile
    from pathlib import Path

    from worker_cpu.ffmpeg import loops as lp
    from schema.models import BaseLoop

    binary = _find_ffmpeg()
    if binary is None:
        log.warning("loop_preprocess_waiting_for_ffmpeg", loop_id=loop_id)
        return

    with open_session() as session:
        loop = session.get(BaseLoop, uuid.UUID(loop_id))
        if loop is None:
            raise ValueError(f"loop {loop_id} not found")
        if loop.ping_pong:
            log.info("loop_preprocess_skip_idempotent", loop_id=loop_id)
            return

        store = ObjectStore()
        _, key = store.parse_uri(loop.source_uri)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.mp4"
            store.get_file(key, source)

            ratio = lp.vfr_ratio(binary, source)
            loop.vfr_ratio = ratio
            if ratio > lp.VFR_MAX_RATIO:
                # reject at ingest — never discover drift at assembly
                loop.error = f"VFR source rejected at ingest (ratio {ratio:.3f})"
                session.add(loop)
                session.commit()
                log.warning("loop_rejected_vfr", loop_id=loop_id, ratio=ratio)
                return

            score = lp.seam_score(binary, source, tmp_path)
            loop.seam_score = score
            if score > lp.SEAM_MAX_SCORE:
                pingpong = lp.make_ping_pong(binary, source, tmp_path / "pingpong.mp4")
                uri = store.put_file(f"loops/{loop_id}/pingpong.mp4", pingpong)
                loop.source_uri = uri
                loop.frame_count = loop.frame_count * 2
                loop.ping_pong = True
                log.info("loop_ping_pong_fallback", loop_id=loop_id, seam_score=score)

        loop.error = None
        session.add(loop)
        session.commit()
        log.info("loop_preprocess_done", loop_id=loop_id, vfr_ratio=ratio, seam_score=loop.seam_score)


def derived_prefix(asset_id: str) -> str:
    """Derived artifacts live at a conventional prefix — no schema needed."""
    return f"assets/derived/{asset_id}"


@timed_stage("ingest")
def ingest_stage(asset_id: str) -> dict | None:
    """Produce editor derivatives for one asset: 720p proxy, scrub sprite
    sheet + WebVTT index, waveform peaks. Idempotent: existing derivatives
    are not rebuilt. Non-video assets are skipped gracefully."""
    import json
    import tempfile
    from pathlib import Path

    from worker_cpu.ffmpeg import ingest as ing

    binary = _find_ffmpeg()
    if binary is None:
        log.warning("ingest_waiting_for_ffmpeg", asset_id=asset_id)
        return None

    store = ObjectStore()
    prefix = derived_prefix(asset_id)
    if store.exists(f"{prefix}/proxy.mp4"):
        log.info("ingest_skip_idempotent", asset_id=asset_id)
        return None

    with open_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is None:
            raise ValueError(f"asset {asset_id} not found")
        _, key = store.parse_uri(asset.uri)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source"
        store.get_file(key, src)

        info = ing.probe(binary, src)
        if not info["duration_ms"] or not info["width"]:
            log.info("ingest_skip_not_video", asset_id=asset_id)
            return None

        proxy = ing.make_proxy(binary, src, tmp_path / "proxy.mp4", info["has_audio"])
        store.put_file(f"{prefix}/proxy.mp4", proxy)

        poster = ing.make_poster(binary, src, tmp_path / "poster.jpg", info["duration_ms"])
        store.put_file(f"{prefix}/poster.jpg", poster)

        plan = ing.sprite_plan(info["duration_ms"], info["width"], info["height"])
        sprite = ing.make_sprites(binary, src, tmp_path / "sprite.jpg", plan)
        store.put_file(f"{prefix}/sprite.jpg", sprite)
        vtt = ing.make_vtt(plan, info["duration_ms"])
        store.put_bytes(f"{prefix}/sprite.vtt", vtt.encode(), content_type="text/vtt")

        peaks = ing.waveform_peaks(binary, src)
        store.put_bytes(
            f"{prefix}/peaks.json", json.dumps(peaks).encode(), content_type="application/json"
        )

    with open_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is not None and asset.duration_ms is None:
            asset.duration_ms = info["duration_ms"]
            session.add(asset)
            session.commit()

    log.info("ingest_done", asset_id=asset_id, duration_ms=info["duration_ms"], peaks=len(peaks))

    # Tail of the ingest fan-out (M24): now that a poster frame exists,
    # auto-caption the asset so the resolver can find it by content.
    # Best-effort — derivatives must land even if the queue is unreachable
    # (the direct-invocation path in tests and scripts has no Redis).
    try:
        from pipeline_core.dispatch import Dispatcher
        from pipeline_core.queues import QUEUE_CPU

        Dispatcher().enqueue(
            QUEUE_CPU, "worker_cpu.stages.caption_stage", asset_id, job_key=f"caption-{asset_id}"
        )
    except Exception:
        log.warning("caption_enqueue_failed", asset_id=asset_id)
    return info


_captioner = None


def _get_captioner():
    # one load per worker process, like every model in this codebase
    global _captioner
    if _captioner is None:
        from pipeline_core.captioner import get_captioner

        _captioner = get_captioner()
    return _captioner


_IMAGE_SUFFIXES = {"png", "jpg", "jpeg", "webp"}


@timed_stage("caption")
def caption_stage(asset_id: str, force: bool = False) -> str | None:
    """Auto-caption one asset from its poster frame (or the image itself) and
    re-embed for the resolver. Idempotent: a real, human-or-model caption is
    never overwritten unless force=True (the --recaption path)."""
    from pipeline_core.captioner import is_placeholder_caption

    with open_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is None:
            raise ValueError(f"asset {asset_id} not found")
        if not force and not is_placeholder_caption(asset.caption):
            log.info("caption_skip_has_caption", asset_id=asset_id)
            return None
        uri = asset.uri

    store = ObjectStore()
    poster_key = f"{derived_prefix(asset_id)}/poster.jpg"
    if store.exists(poster_key):
        image_bytes = store.get_bytes(poster_key)
    elif uri.rsplit(".", 1)[-1].lower() in _IMAGE_SUFFIXES:
        _, key = store.parse_uri(uri)
        image_bytes = store.get_bytes(key)
    else:
        log.info("caption_skip_no_frame", asset_id=asset_id)
        return None

    captioner = _get_captioner()
    caption = captioner.caption(image_bytes)
    if caption is None:
        if not captioner.available:
            log.warning("caption_skipped_no_model", asset_id=asset_id,
                        hint="pip install -e '.[caption]'")
        return None

    with open_session() as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        if asset is None:
            return None
        asset.caption = caption
        asset.embedding = get_embedder().embed(caption)
        session.add(asset)
        session.commit()
    log.info("caption_done", asset_id=asset_id, caption=caption[:80])
    return caption


# Cached like the engines: one client per worker process. Tests inject fakes.
_youtube_client = None


def get_youtube_client():
    global _youtube_client
    if _youtube_client is None:
        from worker_cpu.publish import build_client

        _youtube_client = build_client()
    return _youtube_client


@timed_stage("publish")
def publish_stage(job_id: str) -> None:
    """M6: upload the assembled render. Private always (C5), synthetic-media
    disclosure always (C2), provenance record required (C4). Quota exhaustion
    leaves the job in publishing for the next window; real failures retry
    with exponential backoff, then fail the job."""
    import tempfile
    import time
    from pathlib import Path

    from sqlmodel import select

    from worker_cpu.publish import BACKOFF_BASE_S, UPLOAD_MAX_ATTEMPTS, QuotaExceededError
    from schema.models import JobStatus as JS, PublishRecord, utcnow

    client = get_youtube_client()
    if client is None:
        log.warning("publish_waiting_for_oauth", job_id=job_id)
        return

    with open_session() as session:
        job = session.get(RenderJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status != JS.publishing:
            log.info("publish_skip_idempotent", job_id=job_id, status=job.status.value)
            return
        record = session.exec(
            select(PublishRecord).where(PublishRecord.job_id == job.id)
        ).first()
        if record is None:  # C4: no provenance record, no upload — ever
            fail_job(session, job, "publish: no provenance record (C4)")
            raise ValueError(f"job {job_id}: publish without provenance record")
        if record.youtube_id:
            log.info("publish_skip_already_uploaded", job_id=job_id, youtube_id=record.youtube_id)
            return
        if not job.output_uri:
            fail_job(session, job, "publish: no assembled output to upload")
            raise ValueError(f"job {job_id}: nothing assembled")

        store = ObjectStore()
        _, key = store.parse_uri(job.output_uri)
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "final.mp4"
            store.get_file(key, local)

            description = "Synthetic media — created with an AI avatar pipeline."
            last_error: Exception | None = None
            for attempt in range(UPLOAD_MAX_ATTEMPTS):
                try:
                    result = client.upload(local, job.title, description)
                    break
                except QuotaExceededError:
                    # next quota window, not a failure — leave in publishing
                    log.warning("publish_quota_exhausted", job_id=job_id)
                    return
                except Exception as exc:
                    last_error = exc
                    log.warning("publish_retry", job_id=job_id, attempt=attempt, error=str(exc))
                    time.sleep(BACKOFF_BASE_S * (2**attempt))
            else:
                fail_job(session, job, f"publish: {last_error}")
                raise RuntimeError(f"publish failed for {job_id}: {last_error}")

        record.youtube_id = result.video_id
        record.published_at = utcnow()
        session.add(record)
        advance_job(session, job, JS.published)
        log.info("publish_done", job_id=job_id, youtube_id=result.video_id)


@timed_stage("generation")
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
    import re as _re

    stock = StockResult(**result)
    if not stock.license or not stock.source_url:
        raise ValueError("stock ingest requires license and source_url")
    # The ingest body arrives from the client (relayed search result), so
    # treat it as untrusted: only fetch over https, and only build keys from
    # characters that cannot escape the assets/stock/ prefix or collide with
    # other artefact namespaces in the bucket.
    from urllib.parse import urlsplit

    if urlsplit(stock.download_url).scheme != "https":
        raise ValueError("stock download_url must be https")
    provider = _re.sub(r"[^A-Za-z0-9_-]", "_", stock.provider)[:40]
    external_id = _re.sub(r"[^A-Za-z0-9_-]", "_", stock.external_id)[:80]
    if not provider or not external_id:
        raise ValueError("stock ingest requires provider and external_id")

    store = ObjectStore()
    data = download(stock.download_url)
    extension = "mp4" if stock.kind == "video" else "jpg"
    key = f"assets/stock/{provider}/{external_id}.{extension}"
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
