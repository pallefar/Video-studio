from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from api.db import get_session
from api.main import create_app
from schema.models import BaseLoop, VoiceProfile


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
def client(engine):
    app = create_app()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client


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
