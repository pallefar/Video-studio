"""M18: Speak-style emotion controls on TTS segments, and the per-segment
re-render flow that carries them (the M7 button's backend). Delivery presets
are data; the segment pins its preset next to its seed so a re-render
reproduces the take."""

from __future__ import annotations

import uuid

import pytest
from redis import Redis
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_gpu.stages as gpu_stages
from pipeline_core.emotions import DEFAULT_EMOTION, EMOTIONS, EmotionError, emotion_params
from pipeline_core.queues import QUEUE_GPU
from pipeline_core.segmenting import make_segments
from schema.models import BaseLoop, JobStatus, RenderJob, Segment, VoiceProfile
from tests.conftest import make_job_payload


# --- registry ---------------------------------------------------------------


def test_emotion_params_resolution():
    assert emotion_params("excited")["exaggeration"] == 0.9
    assert emotion_params(None) == EMOTIONS[DEFAULT_EMOTION]
    with pytest.raises(EmotionError):
        emotion_params("sarcastic-nope")


def test_emotions_endpoint_lists_presets(client):
    presets = client.get("/emotions").json()
    ids = {p["id"] for p in presets}
    assert "neutral" in ids and "excited" in ids
    assert all("exaggeration" in p and "cfg_weight" in p for p in presets)


# --- per-segment re-render with emotion --------------------------------------


def _job_in_review(client, session, voice, loop) -> tuple[str, list[Segment]]:
    job = client.post("/jobs", json=make_job_payload(voice, loop)).json()
    row = session.get(RenderJob, uuid.UUID(job["id"]))
    row.status = JobStatus.review
    session.add(row)
    segments = list(
        session.exec(select(Segment).where(Segment.job_id == row.id).order_by(Segment.idx))
    )
    for segment in segments:
        segment.audio_uri = f"s3://test/{segment.idx}.wav"
        segment.duration_ms = 1500
        session.add(segment)
    session.commit()
    return job["id"], segments


def test_rerender_sets_emotion_and_requeues_only_that_segment(client, session, voice, loop, dispatcher):
    job_id, segments = _job_in_review(client, session, voice, loop)
    pinned_seed = segments[0].seed

    response = client.post(f"/jobs/{job_id}/segments/0/rerender", json={"emotion": "excited"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["segments"][0]["emotion"] == "excited"
    assert body["segments"][0]["audio_uri"] is None  # this one re-renders
    assert body["segments"][0]["seed"] == pinned_seed  # same take, new delivery
    assert body["segments"][1]["audio_uri"] is not None  # the rest stay done

    # job creation already enqueued once; the re-render enqueue is the latest
    queue, func_path, args, _ = dispatcher.calls[-1]
    assert queue == QUEUE_GPU
    assert func_path == "worker_gpu.stages.tts_stage"
    assert args == (job_id,)


def test_rerender_reseed_changes_seed(client, session, voice, loop, dispatcher):
    job_id, segments = _job_in_review(client, session, voice, loop)
    pinned_seed = segments[0].seed
    body = client.post(f"/jobs/{job_id}/segments/0/rerender", json={"reseed": True}).json()
    assert body["segments"][0]["seed"] != pinned_seed
    assert body["segments"][0]["emotion"] is None  # emotion untouched when not provided


def test_rerender_validates_emotion_and_state(client, session, voice, loop):
    job_id, _ = _job_in_review(client, session, voice, loop)
    unknown = client.post(f"/jobs/{job_id}/segments/0/rerender", json={"emotion": "smug"})
    assert unknown.status_code == 422

    missing = client.post(f"/jobs/{job_id}/segments/99/rerender", json={})
    assert missing.status_code == 404

    job = client.post("/jobs", json=make_job_payload(voice, loop, title="still queued")).json()
    not_review = client.post(f"/jobs/{job['id']}/segments/0/rerender", json={})
    assert not_review.status_code == 409


# --- the worker passes delivery params to the engine -------------------------


def test_tts_stage_passes_emotion_params_to_engine(engine, redis_url, monkeypatch):
    from tests.test_pipeline_flow import FakeLipsync, FakeTTS

    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    fake_tts = FakeTTS()
    monkeypatch.setattr(gpu_stages, "_engines", (fake_tts, FakeLipsync()))
    Redis.from_url(redis_url).flushall()

    with Session(engine) as session:
        voice = VoiceProfile(name="karsten", reference_audio_uri="s3://test/v.wav")
        loop = BaseLoop(name="desk", source_uri="s3://test/l.mp4", fps=25.0, frame_count=750)
        session.add(voice)
        session.add(loop)
        session.commit()
        job = RenderJob(
            title="emotion e2e", script="One. Two.",
            voice_profile_id=voice.id, base_loop_id=loop.id,
        )
        session.add(job)
        session.commit()
        segments = make_segments(job.id, job.script)
        segments[1].emotion = "urgent"
        for segment in segments:
            session.add(segment)
        session.commit()
        job_id = str(job.id)

    gpu_stages.tts_stage(job_id)

    assert fake_tts.emotions[0] == EMOTIONS["neutral"]  # None falls back
    assert fake_tts.emotions[1] == EMOTIONS["urgent"]
