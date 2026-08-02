"""Phase 2 Plan 02: makes REQ-loop-preprocessing's own acceptance command
measurable. Two halves of one contract, proven together on this CUDA-less
Mac with in-memory SQLite and fake engines:

  - the writer: worker_gpu.stages.lipsync_stage records a metric ref that
    names both the job and the loop (pipeline_core.metrics.lipsync_metric_ref),
    and the idempotent skip path records nothing at all
  - the reader: scripts/bench.py::bench_loop queries by the shared suffix
    helper (pipeline_core.metrics.lipsync_ref_suffix) instead of a substring
    match that can never find a real row

A future change to either half alone breaks a test in this file — that is
the point: these two already drifted apart once, and the result was an
acceptance criterion that could never be met by any implementation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_gpu.stages as gpu_stages
from pipeline_core.metrics import LIPSYNC_STAGE, lipsync_metric_ref, lipsync_ref_suffix
from schema.models import BaseLoop, JobStatus, Metric, RenderJob, Segment, VoiceProfile


# --- fakes -------------------------------------------------------------------


class _FakeTTS:
    def synthesize_segment(self, job_id, idx, text, seed, emotion=None):
        return f"s3://test/jobs/{job_id}/tts/{idx}.wav", 1000


class _FakeLipsync:
    def __init__(self):
        self.calls: list[tuple] = []

    def sync_chunk(self, job_id, loop_id, start_ms, end_ms):
        self.calls.append((job_id, loop_id, start_ms, end_ms))
        return f"s3://test/jobs/{job_id}/lipsync/{start_ms}_{end_ms}.mp4"


class _RaisingLipsync:
    """Proves the idempotent skip never reaches the engine."""

    def sync_chunk(self, *args, **kwargs):
        raise AssertionError("engine must not be invoked on an idempotent skip")


class _ExplodingLipsync:
    def sync_chunk(self, *args, **kwargs):
        raise RuntimeError("engine exploded")


# --- fixtures ------------------------------------------------------------


def _make_loop_and_voice(session) -> tuple[VoiceProfile, BaseLoop]:
    voice = VoiceProfile(name="v", reference_audio_uri="s3://test/v.wav")
    loop = BaseLoop(name="desk", source_uri="s3://test/l.mp4", fps=25.0, frame_count=100)
    session.add(voice)
    session.add(loop)
    session.commit()
    session.refresh(voice)
    session.refresh(loop)
    return voice, loop


def _make_queued_job(session) -> tuple[str, str]:
    """A job at its default queued status with one segment pending audio —
    ready for tts_stage."""
    voice, loop = _make_loop_and_voice(session)
    job = RenderJob(title="t", script="One.", voice_profile_id=voice.id, base_loop_id=loop.id)
    session.add(job)
    session.commit()
    session.add(Segment(job_id=job.id, idx=0, text="One.", pause_after_ms=0))
    session.commit()
    return str(job.id), str(loop.id)


def _make_lipsync_ready_job(session, *, status: JobStatus = JobStatus.lipsync) -> tuple[str, str]:
    """A job with two fully-voiced segments, parked at the given status —
    ready for lipsync_stage."""
    voice, loop = _make_loop_and_voice(session)
    job = RenderJob(
        title="t", script="One. Two.",
        voice_profile_id=voice.id, base_loop_id=loop.id, status=status,
    )
    session.add(job)
    session.commit()
    session.add(Segment(
        job_id=job.id, idx=0, text="One.", duration_ms=1000, pause_after_ms=100,
        audio_uri="s3://test/a0.wav",
    ))
    session.add(Segment(
        job_id=job.id, idx=1, text="Two.", duration_ms=1000, pause_after_ms=0,
        audio_uri="s3://test/a1.wav",
    ))
    session.commit()
    return str(job.id), str(loop.id)


def _lipsync_rows(engine) -> list[Metric]:
    with Session(engine) as check:
        return list(check.exec(select(Metric).where(Metric.stage == LIPSYNC_STAGE)).all())


# --- Test 1-3: the ref/suffix contract, by construction -----------------------


def test_ref_and_suffix_agree_by_construction():
    ref = lipsync_metric_ref("job-1", "loop-1")
    assert "job-1" in ref
    assert ref.endswith(lipsync_ref_suffix("loop-1"))


def test_ref_suffix_no_cross_loop_collision():
    ref = lipsync_metric_ref("job-1", "loop-b")
    assert not ref.endswith(lipsync_ref_suffix("loop-a"))


def test_legacy_job_only_ref_carries_no_loop_suffix():
    """Pre-fix rows recorded ref = str(job_id) alone — a UUID's canonical
    form contains no colon, so it can never carry any loop's suffix."""
    legacy_ref = str(uuid.uuid4())
    assert not legacy_ref.endswith(lipsync_ref_suffix(str(uuid.uuid4())))
    assert not legacy_ref.endswith(lipsync_ref_suffix(legacy_ref))


# --- Test 4-6: the writer half — worker_gpu.stages.lipsync_stage ------------


def test_lipsync_completion_writes_one_row_with_shared_ref(engine, session, monkeypatch, fake_gpu_redis):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    job_id, loop_id = _make_lipsync_ready_job(session)

    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (None, _FakeLipsync()))
    monkeypatch.setattr(gpu_stages.Dispatcher, "enqueue", lambda self, *a, **kw: None)

    gpu_stages.lipsync_stage(job_id)

    rows = _lipsync_rows(engine)
    assert len(rows) == 1
    assert rows[0].ref == lipsync_metric_ref(job_id, loop_id)


def test_idempotent_skip_records_no_row(engine, session, monkeypatch, fake_gpu_redis):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    job_id, _loop_id = _make_lipsync_ready_job(session, status=JobStatus.assemble)

    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (None, _RaisingLipsync()))
    monkeypatch.setattr(gpu_stages.Dispatcher, "enqueue", lambda self, *a, **kw: None)

    gpu_stages.lipsync_stage(job_id)  # must not raise — the engine would if called

    assert _lipsync_rows(engine) == []


def test_failed_lipsync_still_records_row(engine, session, monkeypatch, fake_gpu_redis):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    job_id, loop_id = _make_lipsync_ready_job(session)

    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (None, _ExplodingLipsync()))
    monkeypatch.setattr(gpu_stages.Dispatcher, "enqueue", lambda self, *a, **kw: None)

    with pytest.raises(RuntimeError):
        gpu_stages.lipsync_stage(job_id)

    rows = _lipsync_rows(engine)
    assert len(rows) == 1
    assert rows[0].ref == lipsync_metric_ref(job_id, loop_id)
    with Session(engine) as check:
        job = check.get(RenderJob, uuid.UUID(job_id))
        assert job.status == JobStatus.failed


# --- Test 7: tts_stage's ref is untouched ------------------------------------


def test_tts_stage_ref_still_bare_job_id(engine, session, monkeypatch, fake_gpu_redis):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    job_id, _loop_id = _make_queued_job(session)

    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (_FakeTTS(), None))
    monkeypatch.setattr(gpu_stages.Dispatcher, "enqueue", lambda self, *a, **kw: None)

    gpu_stages.tts_stage(job_id)

    with Session(engine) as check:
        rows = list(check.exec(select(Metric).where(Metric.stage == "tts")).all())
    assert len(rows) == 1
    assert rows[0].ref == job_id
