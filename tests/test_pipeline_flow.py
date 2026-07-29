"""End-to-end orchestration: a job goes queued -> tts -> lipsync -> assemble
unattended through real Redis + RQ, with fake engines standing in for the
models (real engine loads are M3 work on the GPU host). Also proves
segment-level idempotency: a second pass re-renders nothing.
"""

from __future__ import annotations

import uuid

import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_gpu.stages as gpu_stages
from pipeline_core.chunking import MAX_WINDOW_MS
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_CPU, QUEUE_GPU, stage_key
from pipeline_core.segmenting import make_segments
from schema.models import BaseLoop, JobStatus, RenderJob, Segment, VoiceProfile

SEGMENT_DURATION_MS = 40_000  # long enough that four segments need two windows


class FakeTTS:
    def __init__(self):
        self.calls: list[tuple[str, int, int]] = []

    def synthesize_segment(self, job_id, idx, text, seed):
        self.calls.append((job_id, idx, seed))
        return f"s3://test/jobs/{job_id}/tts/{idx}.wav", SEGMENT_DURATION_MS


class FakeLipsync:
    def __init__(self):
        self.windows: list[tuple[int, int]] = []

    def sync_chunk(self, job_id, loop_id, start_ms, end_ms):
        self.windows.append((start_ms, end_ms))
        return f"s3://test/jobs/{job_id}/lipsync/{start_ms}_{end_ms}.mp4"


@pytest.fixture()
def pipeline(engine, redis_url, monkeypatch):
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    fake_tts, fake_lipsync = FakeTTS(), FakeLipsync()
    monkeypatch.setattr(gpu_stages, "_engines", (fake_tts, fake_lipsync))

    redis = Redis.from_url(redis_url)
    redis.flushall()

    with Session(engine) as session:
        voice = VoiceProfile(name="karsten", reference_audio_uri="s3://test/v.wav")
        loop = BaseLoop(name="desk", source_uri="s3://test/l.mp4", fps=25.0, frame_count=750)
        session.add(voice)
        session.add(loop)
        session.commit()
        job = RenderJob(
            title="e2e",
            script="One. Two. Three. Four.",
            voice_profile_id=voice.id,
            base_loop_id=loop.id,
        )
        session.add(job)
        session.commit()
        for segment in make_segments(job.id, job.script):
            session.add(segment)
        session.commit()
        job_id = job.id

    return {
        "engine": engine,
        "redis": redis,
        "job_id": job_id,
        "tts": fake_tts,
        "lipsync": fake_lipsync,
    }


def _drain_gpu_queue(redis):
    SimpleWorker([Queue(QUEUE_GPU, connection=redis)], connection=redis).work(burst=True)


def _job_status(engine, job_id) -> JobStatus:
    with Session(engine) as session:
        return session.get(RenderJob, job_id).status


def test_job_runs_unattended_to_assemble(pipeline):
    redis, engine, job_id = pipeline["redis"], pipeline["engine"], pipeline["job_id"]

    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)

    assert _job_status(engine, job_id) == JobStatus.assemble

    with Session(engine) as session:
        segments = session.exec(
            select(Segment).where(Segment.job_id == job_id).order_by(Segment.idx)
        ).all()
    assert len(segments) == 4
    assert all(s.audio_uri and s.duration_ms == SEGMENT_DURATION_MS for s in segments)

    # seeds generated at ingest were passed to the engine, pinned
    assert [seed for (_, _, seed) in pipeline["tts"].calls] == [s.seed for s in segments]

    # lip-sync ran in windows within the 60-90 s bound, covering the timeline
    windows = pipeline["lipsync"].windows
    assert len(windows) >= 2
    assert windows[0][0] == 0
    assert all(end - start <= MAX_WINDOW_MS for start, end in windows)
    total = sum(s.duration_ms + s.pause_after_ms for s in segments)
    assert windows[-1][1] == total

    # the assemble stage was handed off to the cpu queue
    cpu_queue = Queue(QUEUE_CPU, connection=redis)
    assert stage_key(job_id, "assemble") in cpu_queue.job_ids


def test_rerun_is_idempotent(pipeline):
    redis, engine, job_id = pipeline["redis"], pipeline["engine"], pipeline["job_id"]

    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)
    first_tts_calls = len(pipeline["tts"].calls)
    assert first_tts_calls == 4

    # a duplicate delivery (spot instance died mid-ack, safety re-enqueue...)
    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)

    assert len(pipeline["tts"].calls) == first_tts_calls, "segments were re-rendered"
    assert _job_status(engine, job_id) == JobStatus.assemble


def test_assemble_stage_waits_for_m4(pipeline):
    redis, engine, job_id = pipeline["redis"], pipeline["engine"], pipeline["job_id"]

    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)
    SimpleWorker([Queue(QUEUE_CPU, connection=redis)], connection=redis).work(burst=True)

    # ffmpeg chain is M4 — the job waits in assemble instead of failing
    assert _job_status(engine, job_id) == JobStatus.assemble


def test_engine_failure_marks_job_failed_and_retry_reenters(pipeline):
    redis, engine, job_id = pipeline["redis"], pipeline["engine"], pipeline["job_id"]

    class ExplodingTTS:
        def synthesize_segment(self, job_id, idx, text, seed):
            raise RuntimeError("CUDA OOM")

    gpu_stages._engines = (ExplodingTTS(), pipeline["lipsync"])
    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)
    assert _job_status(engine, job_id) == JobStatus.failed
    with Session(engine) as session:
        assert "CUDA OOM" in session.get(RenderJob, job_id).error

    # retry: failed -> queued re-enters the lane and completes with a healthy engine
    with Session(engine) as session:
        job = session.get(RenderJob, job_id)
        job.status = JobStatus.queued
        job.error = None
        session.add(job)
        session.commit()
    gpu_stages._engines = (pipeline["tts"], pipeline["lipsync"])
    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.tts_stage", str(job_id), job_key=stage_key(job_id, "tts")
    )
    _drain_gpu_queue(redis)
    assert _job_status(engine, job_id) == JobStatus.assemble
