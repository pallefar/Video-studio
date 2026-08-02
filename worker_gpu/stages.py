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
from pipeline_core.emotions import emotion_params
from pipeline_core.metrics import timed_stage
from pipeline_core.dispatch import Dispatcher, get_redis
from pipeline_core.locks import HOLDER_RENDER, GpuLockHeld, gpu_lock
from pipeline_core.queues import QUEUE_CPU, QUEUE_GPU, stage_key
from pipeline_core.storage import ObjectStore
from schema.models import (
    BaseLoop,
    Identity,
    IdentityTrainingStatus,
    JobStatus,
    RenderJob,
    Segment,
    utcnow,
)
from worker_gpu.preprocess import loop_cache

log = structlog.get_logger()

# Engines are cached at module level: models load once per worker process and
# stay resident (warmed at boot from run.py at M3). Tests inject fakes here.
_engines = None


def get_engines():
    global _engines
    if _engines is None:
        from pipeline_core.settings import Settings

        store = ObjectStore()
        if Settings().dev_engines:
            # DEV_ENGINES=1: placeholder engines so the full pipeline runs
            # without CUDA (Apple Silicon / CI). Loudly non-production.
            from worker_gpu.engines.dev import DevLipsyncEngine, DevTTSEngine

            tts, lipsync = DevTTSEngine(store), DevLipsyncEngine(store)
        else:
            from worker_gpu.engines.lipsync import MuseTalkEngine
            from worker_gpu.engines.tts import ChatterboxEngine

            tts, lipsync = ChatterboxEngine(store), MuseTalkEngine(store)
        tts.load()
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
                        job_id, segment.idx, segment.text, segment.seed,
                        emotion=emotion_params(segment.emotion),
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


@timed_stage("loop_cache")
def loop_cache_stage(loop_id: str) -> None:
    """M2 (GPU half): builds MuseTalk's persisted latent/bbox cache for a
    loop once CPU preprocessing has finished (worker_cpu.stages
    .loop_preprocess_stage's chain, on both its success tail and its
    ping-pong idempotent exit). Idempotent on the loop's own persisted state
    (BaseLoop.latents_uri via loop_cache.cache_is_present) — this cache is
    loop-scoped, not job-scoped, so there is no job row here.

    Resolves the engine and checks cache_is_present BEFORE acquiring the GPU
    lock, so a no-op never takes the card away from a waiting render. If the
    resident lip-sync engine exposes no `prepare_loop_cache` seam — true
    today, and true under DEV_ENGINES=1 on any Mac — logs a loud structured
    warning naming the engine class and returns without touching the
    columns, keeping ./scripts/dev_up.sh and CI green while making the
    Phase-1 dependency visible in the logs rather than as a crash."""
    store = ObjectStore()
    with open_session() as session:
        loop = session.get(BaseLoop, uuid.UUID(loop_id))
        if loop is None:
            raise ValueError(f"loop {loop_id} not found")
        if loop_cache.cache_is_present(store, loop):
            log.info("loop_cache_skip_idempotent", loop_id=loop_id)
            return

    _, lipsync_engine = get_engines()
    prepare = getattr(lipsync_engine, "prepare_loop_cache", None)
    if prepare is None:
        log.warning(
            "loop_cache_no_preparer", loop_id=loop_id,
            engine=type(lipsync_engine).__name__,
        )
        return

    try:
        with gpu_lock(get_redis(), HOLDER_RENDER):
            loop_cache.build_loop_cache(store, loop_id, prepare)
    except GpuLockHeld:
        raise  # transient — the loop stays uncached, a re-enqueue retries
    except Exception as exc:
        # there is no job row to fail here — the loop simply stays uncached
        log.warning("loop_cache_build_failed", loop_id=loop_id, error=str(exc))
        raise


@timed_stage("generation")
def generation_stage_local(generation_id: str) -> None:
    """Local (wan-lane) generation: exclusive GPU lock, never concurrent with
    the render lane."""
    from pipeline_core.generation import run_generation
    from pipeline_core.locks import HOLDER_WAN

    with gpu_lock(get_redis(), HOLDER_WAN):
        run_generation(generation_id)


@timed_stage("generation")
def generation_stage_shared(generation_id: str) -> None:
    """Shared-lane generation (M18): rides the render queue under the render
    holder — ACE-Step and the other shared residents never take the wan
    lane's exclusive lock, and can never run concurrently with it."""
    from pipeline_core.generation import run_generation

    with gpu_lock(get_redis(), HOLDER_RENDER):
        run_generation(generation_id)


# Cached like the render engines: the trainer loads once per worker process.
_trainer = None


def get_trainer():
    global _trainer
    if _trainer is None:
        from worker_gpu.engines.identity import IdentityLoraTrainer

        _trainer = IdentityLoraTrainer(ObjectStore())
        _trainer.load()
    return _trainer


@timed_stage("identity_train")
def identity_training_stage(identity_id: str) -> None:
    """Identity LoRA training (M17): wan lane, exclusive GPU lock, overnight
    batch. C6 defence in depth — the API edge already refused unconsented
    identities, but the worker re-checks so no path around the route (a raw
    enqueue, a replayed job) can train without recorded consent."""
    from pipeline_core.locks import HOLDER_WAN

    with open_session() as session:
        identity = session.get(Identity, uuid.UUID(identity_id))
        if identity is None:
            raise ValueError(f"identity {identity_id} not found")
        if identity.training_status == IdentityTrainingStatus.trained and identity.lora_uri:
            log.info("identity_train_skip_idempotent", identity_id=identity_id)
            return
        if not identity.consent_recorded_by or identity.consent_at is None:
            identity.training_status = IdentityTrainingStatus.failed
            identity.error = "C6: no recorded consent — training refused"
            identity.updated_at = utcnow()
            session.add(identity)
            session.commit()
            raise ValueError(f"C6: identity {identity_id} has no recorded consent")

        identity.training_status = IdentityTrainingStatus.training
        identity.updated_at = utcnow()
        session.add(identity)
        session.commit()
        try:
            with gpu_lock(get_redis(), HOLDER_WAN):
                lora_uri = get_trainer().train(identity_id, list(identity.reference_asset_ids))
        except GpuLockHeld:
            identity.training_status = IdentityTrainingStatus.queued
            identity.updated_at = utcnow()
            session.add(identity)
            session.commit()
            raise  # transient — a re-enqueue resumes it
        except Exception as exc:
            identity.training_status = IdentityTrainingStatus.failed
            identity.error = f"train: {exc}"
            identity.updated_at = utcnow()
            session.add(identity)
            session.commit()
            raise
        identity.lora_uri = lora_uri
        identity.training_status = IdentityTrainingStatus.trained
        identity.error = None
        identity.updated_at = utcnow()
        session.add(identity)
        session.commit()
        log.info("identity_train_done", identity_id=identity_id, lora_uri=lora_uri)
