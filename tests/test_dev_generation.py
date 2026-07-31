"""Dev generation executor (DEV_ENGINES=1): every local generation kind
produces real bytes end-to-end without CUDA — presets, images, music,
upscales, and storyboard exports containing generated shots."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_gpu.stages as gpu_stages
from pipeline_core.dev_generation import DevGenerationExecutor
from pipeline_core.generation import run_generation
from pipeline_core.providers import LocalWanProvider, ProviderRegistry, build_registry
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, Generation, GenerationKind, GenerationStatus


@pytest.fixture()
def store():
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="devgen-test"))
        store.ensure_bucket()
        yield store


def _generation(kind: GenerationKind, prompt="a fox in the snow", **params) -> Generation:
    return Generation(provider="local", model="wan2.2-t2v", kind=kind,
                      prompt=prompt, params=params)


# --- per-kind synthesis ------------------------------------------------------


def test_video_kind_produces_mp4_at_requested_dims(store):
    executor = DevGenerationExecutor(store)
    result = executor.generate(
        _generation(GenerationKind.text_to_video, width=320, height=180, duration_s=1, seed=7)
    )
    assert result.content_type == "video/mp4"
    assert b"ftyp" in result.data[:64]
    assert result.cost == 0.0


def test_aspect_rotates_default_dims(store):
    executor = DevGenerationExecutor(store)
    result = executor.generate(_generation(GenerationKind.text_to_video, aspect="9:16", duration_s=1))
    assert b"ftyp" in result.data[:64]


def test_image_kind_produces_png(store):
    executor = DevGenerationExecutor(store)
    result = executor.generate(_generation(GenerationKind.image, width=256, height=256, seed=3))
    assert result.content_type == "image/png"
    assert result.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_music_kind_produces_wav(store):
    executor = DevGenerationExecutor(store)
    result = executor.generate(_generation(GenerationKind.music, duration_s=2, seed=5))
    assert result.content_type == "audio/wav"
    assert result.data[:4] == b"RIFF" and result.data[8:12] == b"WAVE"


def test_upscale_doubles_source(store):
    executor = DevGenerationExecutor(store)
    small = executor.generate(
        _generation(GenerationKind.text_to_video, width=160, height=90, duration_s=1)
    )
    uri = store.put_bytes("src/clip.mp4", small.data)
    result = executor.generate(
        _generation(GenerationKind.upscale, source_asset_uri=uri)
    )
    assert b"ftyp" in result.data[:64]
    assert len(result.data) > 0


# --- wired through the provider + pipeline -----------------------------------


def test_local_provider_uses_dev_executor_when_enabled(store, monkeypatch):
    provider = LocalWanProvider(settings=Settings(dev_engines=True, s3_endpoint="", s3_bucket="devgen-test"))
    result = provider.generate(_generation(GenerationKind.text_to_video, duration_s=1, width=160, height=96))
    assert b"ftyp" in result.data[:64]


def test_full_preset_flow_lands_asset(client, engine, dispatcher, store, monkeypatch):
    """POST /presets/generate -> wan queue -> generation_stage_local (lock
    faked) -> real placeholder MP4 in the library."""
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setenv("DEV_ENGINES", "1")

    response = client.post(
        "/presets/generate",
        json={"preset_ids": ["crash_zoom_in"], "subject": "a red espresso machine"},
    )
    assert response.status_code == 201, response.text
    generation_id = response.json()["id"]
    (queue, _, _, _), = dispatcher.calls
    assert queue == "wan"

    class NoopLock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(gpu_stages, "gpu_lock", lambda *a, **k: NoopLock())
    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **k: None)
    monkeypatch.setattr(
        "pipeline_core.generation.ObjectStore", lambda *a, **k: store
    )
    gpu_stages.generation_stage_local(generation_id)

    with Session(engine) as session:
        row = session.get(Generation, uuid.UUID(generation_id))
        assert row.status == GenerationStatus.succeeded
        assert row.cost == 0.0
        asset = session.get(Asset, row.asset_id)
        assert asset.uri.endswith(".mp4")
        assert asset.approved is False
        assert len(store.get_bytes(asset.uri.split("/", 3)[-1])) > 500


def test_registry_default_path_raises_config_hint(monkeypatch):
    monkeypatch.delenv("DEV_ENGINES", raising=False)
    monkeypatch.delenv("COMFY_URL", raising=False)
    registry = build_registry(Settings(dev_engines=False, comfy_url="", _env_file=None))
    provider = registry.providers["local"]
    with pytest.raises(Exception, match="COMFY_URL"):
        provider.generate(_generation(GenerationKind.text_to_video))
