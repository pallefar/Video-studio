from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from api.db import get_session
from api.main import create_app
from api.routes.jobs import get_dispatcher
from schema.models import BaseLoop, VoiceProfile


class RecordingDispatcher:
    """Captures enqueues instead of touching Redis — for API unit tests."""

    def __init__(self):
        self.calls: list[tuple[str, str, tuple, str | None]] = []

    def enqueue(self, queue_name, func_path, *args, job_key=None):
        self.calls.append((queue_name, func_path, args, job_key))


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture()
def dispatcher():
    return RecordingDispatcher()


@pytest.fixture()
def client(engine, dispatcher):
    app = create_app()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def redis_url(tmp_path_factory):
    """A real redis-server on a unix socket, shared across the session."""
    import shutil
    import subprocess
    import time

    if shutil.which("redis-server") is None:
        pytest.skip("redis-server not available")
    sock = tmp_path_factory.mktemp("redis") / "redis.sock"
    proc = subprocess.Popen(
        [
            "redis-server",
            "--port", "0",
            "--unixsocket", str(sock),
            "--save", "",
            "--appendonly", "no",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(200):
        if sock.exists():
            break
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail("redis-server did not start")
    yield f"unix://{sock}"
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture()
def voice(session) -> VoiceProfile:
    voice = VoiceProfile(
        name="karsten",
        version=2,
        reference_audio_uri="s3://avatar-pipeline/voices/karsten_v2/ref.wav",
    )
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@pytest.fixture()
def loop(session) -> BaseLoop:
    loop = BaseLoop(
        name="desk-neutral",
        source_uri="s3://avatar-pipeline/loops/desk-neutral/source.mp4",
        fps=25.0,
        frame_count=750,
    )
    session.add(loop)
    session.commit()
    session.refresh(loop)
    return loop


def make_job_payload(voice: VoiceProfile, loop: BaseLoop, **overrides) -> dict:
    payload = {
        "title": "Why your backlog is lying to you",
        "script": "First sentence. Second sentence.",
        "voice_profile_id": str(voice.id),
        "base_loop_id": str(loop.id),
    }
    payload.update(overrides)
    return payload


def make_uuid() -> str:
    return str(uuid.uuid4())
