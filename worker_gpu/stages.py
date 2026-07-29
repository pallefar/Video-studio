"""GPU stage functions consumed from the render queue.

Each stage is idempotent: tts skips segments that already have audio, and a
stage invoked on a job that has moved past it is a no-op. Engine work runs
under the exclusive GPU lock so the render lane and the Wan B-roll lane can
never hold the card simultaneously.
"""

from __future__ import annotations

import uuid

import structlog
from sqlmodel import select

from pipeline_core.chunking import chunk_windows
from pipeline_core.db import advance_job, fail_job, open_session
from pipeline_core.metrics import timed_stage
from pipeline_core.dispatch import Dispatcher, get_redis
from pipeline_core.locks import HOLDER_RENDER, GpuLockHeld, gpu_lock
from pipeline_core.queues import QUEUE_CPU, QUEUE_GPU, stage_key
from pipeline_core.storage import ObjectStore
from schema.models import JobStatus, RenderJob, Segment

log = structlog.get_logger()

# Engines are cached at module level: models load once per worker process and
# stay resident (warmed at boot from run.py at M3). Tests inject fakes here.
_engines = None


def get_engines():
    global _engines
    if _engines is None:
        from worker_gpu.engines.lipsync import MuseTalkEngine
        from worker_gpu.engines.tts import ChatterboxEngine

        store = ObjectStore()
        tts = ChatterboxEngine(store)
        tts.load()
        lipsync = MuseTalkEngine(store)
        lipsync.load()
        _engines = (tts, lipsync)
    return _engines


def _get_job(session, job_id: str) -> RenderJob:
    job = session.get(RenderJob, uuid.UUID(job_id))
    if job is None:
        raise ValueError(f"job {job_id} not found")
    return job


def _segments(session, job_id: str) -> list[Segment]:
    return list(
        session.exec(
            select(Segment).where(Segment.job_id == uuid.UUID(job_id)).order_by(Segment.idx)
        ).all()
    )


@timed_stage("tts")
def tts_stage(job_id: str) -> None:
    with open_session() as session:
        job = _get_job(session, job_id)
        if job.status not in (JobStatus.queued, JobStatus.tts):
            log.info("tts_skip_idempotent", job_id=job_id, status=job.status.value)
            return
        if job.status == JobStatus.queued:
            advance_job(session, job, JobStatus.tts)

        pending = [s for s in _segments(session, job_id) if s.audio_uri is None]
        tts_engine, _ = get_engines()
        try:
            with gpu_lock(get_redis(), HOLDER_RENDER):
                for segment in pending:
                    audio_uri, duration_ms = tts_engine.synthesize_segment(
                        job_id, segment.idx, segment.text, segment.seed
                    )
                    segment.audio_uri = audio_uri
                    segment.duration_ms = duration_ms
                    session.add(segment)
                    session.commit()  # per segment, so a crash loses at most one
                    log.info("tts_segment_done", job_id=job_id, idx=segment.idx, seed=segment.seed)
        except GpuLockHeld:
            raise  # transient — leave the job in tts, a re-enqueue resumes it
        except Exception as exc:
            fail_job(session, job, f"tts: {exc}")
            raise
        advance_job(session, job, JobStatus.lipsync)

    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.lipsync_stage", job_id, job_key=stage_key(job_id, "lipsync")
    )


@timed_stage("lipsync")
def lipsync_stage(job_id: str) -> None:
    with open_session() as session:
        job = _get_job(session, job_id)
        if job.status != JobStatus.lipsync:
            log.info("lipsync_skip_idempotent", job_id=job_id, status=job.status.value)
            return

        segments = _segments(session, job_id)
        missing = [s.idx for s in segments if s.duration_ms is None]
        if missing:
            raise ValueError(f"job {job_id}: segments without audio: {missing}")

        spans = [s.duration_ms + s.pause_after_ms for s in segments]
        windows = chunk_windows(spans)
        _, lipsync_engine = get_engines()
        try:
            with gpu_lock(get_redis(), HOLDER_RENDER):
                for start_ms, end_ms in windows:
                    lipsync_engine.sync_chunk(job_id, str(job.base_loop_id), start_ms, end_ms)
                    log.info("lipsync_chunk_done", job_id=job_id, start_ms=start_ms, end_ms=end_ms)
        except GpuLockHeld:
            raise
        except Exception as exc:
            fail_job(session, job, f"lipsync: {exc}")
            raise
        advance_job(session, job, JobStatus.assemble)

    Dispatcher().enqueue(
        QUEUE_CPU, "worker_cpu.stages.assemble_stage", job_id, job_key=stage_key(job_id, "assemble")
    )


@timed_stage("generation")
def generation_stage_local(generation_id: str) -> None:
    """Local (wan-lane) generation: exclusive GPU lock, never concurrent with
    the render lane."""
    from pipeline_core.generation import run_generation
    from pipeline_core.locks import HOLDER_WAN

    with gpu_lock(get_redis(), HOLDER_WAN):
        run_generation(generation_id)
