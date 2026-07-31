"""Dev-engines mode (DEV_ENGINES=1): the full avatar pipeline without CUDA —
what an Apple Silicon Mac runs. Placeholder voice + static avatar, but the
real stages, real chunking, real assembly, real compliance output."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
import worker_gpu.stages as gpu_stages
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import BaseLoop, JobStatus, RenderJob, Segment, VoiceProfile
from worker_gpu.engines.dev import DevLipsyncEngine, DevTTSEngine


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


def test_get_engines_selects_dev_engines(monkeypatch):
    monkeypatch.setattr(gpu_stages, "_engines", None)
    monkeypatch.setenv("DEV_ENGINES", "1")
    try:
        tts, lipsync = gpu_stages.get_engines()
        assert isinstance(tts, DevTTSEngine)
        assert isinstance(lipsync, DevLipsyncEngine)
    finally:
        gpu_stages._engines = None  # never leak dev engines into other tests


def test_real_engines_remain_the_default(monkeypatch):
    monkeypatch.setattr(gpu_stages, "_engines", None)
    monkeypatch.delenv("DEV_ENGINES", raising=False)
    try:
        # ChatterboxEngine.load requires CUDA — proving dev mode is opt-in
        with pytest.raises((RuntimeError, NotImplementedError, ImportError)):
            gpu_stages.get_engines()
    finally:
        gpu_stages._engines = None


def test_dev_tts_produces_real_wav_with_duration(ffmpeg_bin, monkeypatch):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="dev-tts"))
        store.ensure_bucket()
        engine = DevTTSEngine(store)
        engine.load()
        uri, duration_ms = engine.synthesize_segment(
            "job-1", 0, "Your backlog is not a plan.", seed=42,
            emotion={"exaggeration": 0.9, "cfg_weight": 0.35},
        )
        assert uri.endswith("jobs/job-1/tts/0.wav")
        assert duration_ms > 500  # six words at a speaking pace
        assert len(store.get_bytes("jobs/job-1/tts/0.wav")) > 1000


def test_dev_pipeline_end_to_end(ffmpeg_bin, engine, monkeypatch, tmp_path):
    """queued -> tts -> lipsync -> assemble -> review on dev engines, ending
    in a playable MP4 with the C1 watermark — the Mac experience."""
    import subprocess

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="dev-e2e"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        monkeypatch.setattr(gpu_stages, "_engines", (DevTTSEngine(store), DevLipsyncEngine(store)))
        gpu_stages.get_engines()[0].load()

        # a tiny real base loop in the store
        loop_clip = tmp_path / "loop.mp4"
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
             "-i", "color=c=teal:s=192x108:d=1:r=25", "-pix_fmt", "yuv420p", str(loop_clip)],
            check=True, capture_output=True,
        )
        loop_uri = store.put_file("loops/desk/source.mp4", loop_clip)

        with Session(engine) as session:
            voice = VoiceProfile(name="dev", reference_audio_uri="s3://dev-e2e/v.wav")
            loop = BaseLoop(name="desk", source_uri=loop_uri, fps=25.0, frame_count=25)
            session.add(voice)
            session.add(loop)
            session.commit()
            job = RenderJob(
                title="dev e2e", script="One two three. Four five six.",
                voice_profile_id=voice.id, base_loop_id=loop.id,
            )
            session.add(job)
            session.commit()
            from pipeline_core.segmenting import make_segments

            for segment in make_segments(job.id, job.script):
                session.add(segment)
            session.commit()
            job_id = str(job.id)

        # drive the stages directly (no redis needed: lock bypassed via fakes)
        class NoopLock:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(gpu_stages, "gpu_lock", lambda *a, **k: NoopLock())
        monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **k: None)
        monkeypatch.setattr(gpu_stages.Dispatcher, "enqueue", lambda self, *a, **k: None)

        gpu_stages.tts_stage(job_id)
        gpu_stages.lipsync_stage(job_id)
        cpu_stages.assemble_stage(job_id)

        with Session(engine) as session:
            job = session.get(RenderJob, uuid.UUID(job_id))
            assert job.status == JobStatus.review
            assert job.output_uri.endswith("final.mp4")
            segments = session.exec(select(Segment).where(Segment.job_id == job.id)).all()
            assert all(s.audio_uri and s.duration_ms for s in segments)

        final = tmp_path / "final.mp4"
        final.write_bytes(store.get_bytes(f"jobs/{job_id}/final.mp4"))
        assert final.stat().st_size > 1000
        probe = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(final)], capture_output=True, text=True
        )
        assert "Video: h264" in probe.stderr and "Audio: aac" in probe.stderr
