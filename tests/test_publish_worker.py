"""M6 acceptance (structural): uploads land private always, the disclosure
flag is set programmatically, quota exhaustion is distinguished from real
failure, and publish without a provenance record (C4) is refused."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from worker_cpu.publish import PRIVACY, QuotaExceededError, UploadResult, _is_quota_error, build_client
from schema.models import (
    BaseLoop,
    JobStatus,
    PublishRecord,
    RenderJob,
    VoiceProfile,
)


class FakeYouTube:
    def __init__(self, error: Exception | None = None, fail_times: int = 0):
        self.error = error
        self.fail_times = fail_times
        self.calls: list[tuple[str, str, str]] = []

    def upload(self, path: Path, title: str, description: str) -> UploadResult:
        self.calls.append((str(path), title, description))
        if self.error is not None:
            raise self.error
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("transient 503")
        return UploadResult(video_id="yt-123")


@pytest.fixture()
def published_setup(engine, monkeypatch):
    """A job in publishing with provenance record and assembled output."""
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setattr("time.sleep", lambda *_: None)  # no real backoff waits
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="publish-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        uri = store.put_bytes("jobs/x/final.mp4", b"video-bytes")

        with Session(engine) as session:
            voice = VoiceProfile(name="k", reference_audio_uri="s3://t/v.wav")
            loop = BaseLoop(name="d", source_uri="s3://t/l.mp4", fps=25.0, frame_count=1)
            session.add(voice)
            session.add(loop)
            session.commit()
            job = RenderJob(
                title="Publish me", script="One.", voice_profile_id=voice.id,
                base_loop_id=loop.id, status=JobStatus.publishing, output_uri=uri,
            )
            session.add(job)
            session.commit()
            session.add(PublishRecord(job_id=job.id, reviewed_by="karsten"))
            session.commit()
            job_id = str(job.id)
        yield {"engine": engine, "job_id": job_id}


def _job(engine, job_id) -> RenderJob:
    with Session(engine) as session:
        return session.get(RenderJob, uuid.UUID(job_id))


def _record(engine, job_id) -> PublishRecord:
    with Session(engine) as session:
        return session.exec(
            select(PublishRecord).where(PublishRecord.job_id == uuid.UUID(job_id))
        ).one()


# --- structural guarantees ---------------------------------------------------


def test_no_code_path_can_publish_public():
    assert PRIVACY == "private"
    source = Path("worker_cpu/publish.py").read_text()
    assert '"public"' not in source and "'public'" not in source
    # privacyStatus is bound to the constant, never to a parameter
    assert 'privacyStatus": PRIVACY' in source


def test_quota_error_detection():
    class FakeHttpError(Exception):
        error_details = [{"reason": "quotaExceeded"}]

    class OtherHttpError(Exception):
        error_details = [{"reason": "backendError"}]

    assert _is_quota_error(FakeHttpError())
    assert not _is_quota_error(OtherHttpError())


def test_unconfigured_oauth_returns_no_client():
    assert build_client(Settings(youtube_client_id="", _env_file=None)) is None


# --- the stage ---------------------------------------------------------------


def test_upload_success_publishes_job(published_setup, monkeypatch):
    engine, job_id = published_setup["engine"], published_setup["job_id"]
    fake = FakeYouTube()
    monkeypatch.setattr(cpu_stages, "_youtube_client", fake)

    cpu_stages.publish_stage(job_id)

    assert _job(engine, job_id).status == JobStatus.published
    record = _record(engine, job_id)
    assert record.youtube_id == "yt-123"
    assert record.published_at is not None
    (_, title, description), = fake.calls
    assert title == "Publish me"
    assert "Synthetic media" in description

    # replay is a no-op: already uploaded
    cpu_stages.publish_stage(job_id)
    assert len(fake.calls) == 1


def test_quota_exhaustion_waits_for_next_window(published_setup, monkeypatch):
    engine, job_id = published_setup["engine"], published_setup["job_id"]
    fake = FakeYouTube(error=QuotaExceededError("daily quota"))
    monkeypatch.setattr(cpu_stages, "_youtube_client", fake)

    cpu_stages.publish_stage(job_id)  # must NOT raise and must NOT fail the job

    job = _job(engine, job_id)
    assert job.status == JobStatus.publishing  # parked for the next window
    assert job.error is None
    assert len(fake.calls) == 1  # no retry-hammering


def test_transient_failures_retry_then_fail(published_setup, monkeypatch):
    engine, job_id = published_setup["engine"], published_setup["job_id"]
    fake = FakeYouTube(fail_times=99)  # never succeeds
    monkeypatch.setattr(cpu_stages, "_youtube_client", fake)

    with pytest.raises(RuntimeError):
        cpu_stages.publish_stage(job_id)

    from worker_cpu.publish import UPLOAD_MAX_ATTEMPTS

    assert len(fake.calls) == UPLOAD_MAX_ATTEMPTS  # exponential backoff, bounded
    job = _job(engine, job_id)
    assert job.status == JobStatus.failed  # failed -> queued keeps it retryable


def test_transient_failure_then_success(published_setup, monkeypatch):
    engine, job_id = published_setup["engine"], published_setup["job_id"]
    fake = FakeYouTube(fail_times=2)
    monkeypatch.setattr(cpu_stages, "_youtube_client", fake)

    cpu_stages.publish_stage(job_id)

    assert _job(engine, job_id).status == JobStatus.published
    assert len(fake.calls) == 3


def test_c4_no_provenance_record_refuses_upload(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    fake = FakeYouTube()
    monkeypatch.setattr(cpu_stages, "_youtube_client", fake)
    with Session(engine) as session:
        voice = VoiceProfile(name="k", reference_audio_uri="s3://t/v.wav")
        loop = BaseLoop(name="d", source_uri="s3://t/l.mp4", fps=25.0, frame_count=1)
        session.add(voice)
        session.add(loop)
        session.commit()
        job = RenderJob(
            title="No record", script="One.", voice_profile_id=voice.id,
            base_loop_id=loop.id, status=JobStatus.publishing,
            output_uri="s3://publish-test/jobs/x/final.mp4",
        )
        session.add(job)
        session.commit()
        job_id = str(job.id)

    with pytest.raises(ValueError, match="provenance"):
        cpu_stages.publish_stage(job_id)
    assert _job(engine, job_id).status == JobStatus.failed
    assert fake.calls == []  # nothing was uploaded


def test_unconfigured_client_waits(published_setup, monkeypatch):
    engine, job_id = published_setup["engine"], published_setup["job_id"]
    monkeypatch.setattr(cpu_stages, "_youtube_client", None)
    monkeypatch.setattr(cpu_stages, "get_youtube_client", lambda: None)

    cpu_stages.publish_stage(job_id)  # waits quietly, like a missing ffmpeg

    assert _job(engine, job_id).status == JobStatus.publishing


# --- the route enqueues the worker -------------------------------------------


def test_publish_route_enqueues_stage(client, session, voice, loop, dispatcher):
    from tests.conftest import make_job_payload

    job = client.post("/jobs", json=make_job_payload(voice, loop)).json()
    row = session.get(RenderJob, uuid.UUID(job["id"]))
    row.status = JobStatus.review
    session.add(row)
    session.commit()

    response = client.post(
        f"/jobs/{job['id']}/publish", json={"reviewed_by": "karsten", "altered_content": True}
    )
    assert response.status_code == 201, response.text

    queue, func_path, args, job_key = dispatcher.calls[-1]
    assert queue == QUEUE_CPU
    assert func_path == "worker_cpu.stages.publish_stage"
    assert args == (job["id"],)
    assert job_key == f"{job['id']}-publish"