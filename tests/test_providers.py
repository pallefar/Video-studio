"""M10 acceptance: a fake provider round-trips a generation into the asset
library with full provenance; the registry refuses unknown models; an
API-provider job never touches the GPU lock."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import pipeline_core.dispatch as dispatch
import worker_cpu.stages as cpu_stages
from api.routes.generations import get_registry
from pipeline_core.generation import run_generation
from pipeline_core.providers import (
    CLASS_API,
    FalProvider,
    LocalWanProvider,
    ModelSpec,
    ProviderRegistry,
    UnknownModelError,
    build_registry,
)
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    Generation,
    GenerationKind,
    GenerationStatus,
)

T2V = GenerationKind.text_to_video


class FakeApiProvider:
    provider_class = CLASS_API

    def __init__(self, name="fake", fail=False, cost=0.42):
        self.name = name
        self.fail = fail
        self.cost = cost
        self.calls = 0

    def models(self):
        return [ModelSpec(self.name, "fake-t2v", frozenset({T2V}), CLASS_API)]

    def generate(self, generation):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider exploded")
        from pipeline_core.providers import ProviderResult

        return ProviderResult(data=b"generated-bytes", external_id="ext-1", cost=self.cost)


# --- Registry --------------------------------------------------------------


def test_registry_refuses_unknown_provider_and_model():
    registry = build_registry(Settings(fal_api_key=""))
    with pytest.raises(UnknownModelError):
        registry.resolve("nope", "wan2.2-t2v", T2V)
    with pytest.raises(UnknownModelError):
        registry.resolve("local", "no-such-model", T2V)
    with pytest.raises(UnknownModelError):  # kind mismatch is refused too
        registry.resolve("local", "wan2.2-t2v", GenerationKind.image)


def test_registry_gates_api_providers_on_keys():
    assert "fal" not in build_registry(Settings(fal_api_key="")).providers
    assert "fal" in build_registry(Settings(fal_api_key="k")).providers


# --- Round-trip through the asset library (the acceptance case) ------------


@pytest.fixture()
def gen_env(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    registry = ProviderRegistry()
    provider = FakeApiProvider()
    registry.register(provider)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="gen-test"))
        store.ensure_bucket()
        yield {"engine": engine, "registry": registry, "provider": provider, "store": store}


def _make_generation(engine, provider="fake", model="fake-t2v", fallback=None) -> str:
    with Session(engine) as session:
        generation = Generation(
            provider=provider, model=model, kind=T2V,
            prompt="crash zoom on a coffee cup", fallback=fallback or [],
        )
        session.add(generation)
        session.commit()
        return str(generation.id)


def test_generation_roundtrips_into_asset_library(gen_env):
    generation_id = _make_generation(gen_env["engine"])
    run_generation(generation_id, registry=gen_env["registry"], store=gen_env["store"])

    with Session(gen_env["engine"]) as session:
        generation = session.get(Generation, __import__("uuid").UUID(generation_id))
        assert generation.status == GenerationStatus.succeeded
        assert generation.cost == 0.42
        assert generation.external_id == "ext-1"
        asset = session.get(Asset, generation.asset_id)
        assert asset.origin == AssetOrigin.generated
        assert asset.approved is False  # human approval gate before resolver pickup
        assert asset.caption == "crash zoom on a coffee cup"
        assert asset.embedding
        assert gen_env["store"].get_bytes(f"generations/{generation_id}/output.mp4") == b"generated-bytes"


def test_generation_is_idempotent(gen_env):
    generation_id = _make_generation(gen_env["engine"])
    run_generation(generation_id, registry=gen_env["registry"], store=gen_env["store"])
    run_generation(generation_id, registry=gen_env["registry"], store=gen_env["store"])
    assert gen_env["provider"].calls == 1


def test_generation_failure_without_fallback_marks_failed(gen_env):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider(fail=True))
    generation_id = _make_generation(gen_env["engine"])
    with pytest.raises(RuntimeError):
        run_generation(generation_id, registry=registry, store=gen_env["store"])
    with Session(gen_env["engine"]) as session:
        generation = session.get(Generation, __import__("uuid").UUID(generation_id))
        assert generation.status == GenerationStatus.failed
        assert "provider exploded" in generation.error


def test_fallback_chain_redispatches_next_target(gen_env, dispatcher):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider(name="flaky", fail=True))
    registry.register(FakeApiProvider(name="backup"))
    generation_id = _make_generation(
        gen_env["engine"], provider="flaky",
        fallback=[{"provider": "backup", "model": "fake-t2v"}],
    )
    run_generation(generation_id, registry=registry, store=gen_env["store"], dispatcher=dispatcher)

    with Session(gen_env["engine"]) as session:
        generation = session.get(Generation, __import__("uuid").UUID(generation_id))
        assert generation.status == GenerationStatus.queued
        assert generation.provider == "backup"
        assert generation.fallback == []
    assert [c[0] for c in dispatcher.calls] == ["cpu"]  # api class -> network lane

    run_generation(generation_id, registry=registry, store=gen_env["store"], dispatcher=dispatcher)
    with Session(gen_env["engine"]) as session:
        generation = session.get(Generation, __import__("uuid").UUID(generation_id))
        assert generation.status == GenerationStatus.succeeded


# --- The API lane never touches the GPU lock -------------------------------


def test_api_generation_stage_never_acquires_gpu_lock(gen_env, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network lane touched redis/GPU lock")

    monkeypatch.setattr(dispatch, "get_redis", boom)
    monkeypatch.setattr(
        "pipeline_core.generation.build_registry", lambda *a, **k: gen_env["registry"]
    )
    monkeypatch.setattr("pipeline_core.generation.ObjectStore", lambda: gen_env["store"])

    generation_id = _make_generation(gen_env["engine"])
    cpu_stages.generation_stage_api(generation_id)  # completes without redis

    with Session(gen_env["engine"]) as session:
        generation = session.get(Generation, __import__("uuid").UUID(generation_id))
        assert generation.status == GenerationStatus.succeeded


def test_cpu_worker_source_has_no_gpu_lock_reference():
    source = Path(cpu_stages.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\bgpu_lock\b", source)


# --- API endpoints ---------------------------------------------------------


@pytest.fixture()
def api_registry(client):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


def test_create_generation_refuses_unknown_model(client, api_registry):
    response = client.post(
        "/generations",
        json={"provider": "fake", "model": "no-such", "kind": "text_to_video", "prompt": "x"},
    )
    assert response.status_code == 422


def test_create_generation_routes_api_target_to_cpu_lane(client, api_registry, dispatcher):
    response = client.post(
        "/generations",
        json={"provider": "fake", "model": "fake-t2v", "kind": "text_to_video", "prompt": "orbit shot"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "queued"
    queue_name, func_path, args, _ = dispatcher.calls[-1]
    assert queue_name == "cpu"
    assert func_path == "worker_cpu.stages.generation_stage_api"


def test_create_generation_routes_local_target_to_wan_lane(client, dispatcher):
    registry = build_registry(Settings(fal_api_key=""))
    client.app.dependency_overrides[get_registry] = lambda: registry
    response = client.post(
        "/generations",
        json={"provider": "local", "model": "wan2.2-t2v", "kind": "text_to_video", "prompt": "dolly in"},
    )
    assert response.status_code == 201, response.text
    queue_name, func_path, args, _ = dispatcher.calls[-1]
    assert queue_name == "wan"
    assert func_path == "worker_gpu.stages.generation_stage_local"


def test_catalog_lists_models(client, api_registry):
    catalog = client.get("/generations/catalog").json()
    assert catalog == [
        {
            "provider": "fake",
            "model": "fake-t2v",
            "kinds": ["text_to_video"],
            "provider_class": "api",
            "notes": "",
            "est_cost": None,
        }
    ]


def test_catalog_prices_local_free_and_fal_estimated():
    """B1: engine pickers show price — local models are 0.0 (free, not
    unpriced), fal roster entries carry their per-generation estimate."""
    registry = build_registry(Settings(fal_api_key="k"))
    by_model = {(s.provider, s.model): s for s in registry.catalog()}
    assert by_model[("local", "wan2.2-t2v")].est_cost == 0.0
    assert all(
        spec.est_cost == 0.0 for (prov, _), spec in by_model.items() if prov == "local"
    )
    kling = by_model[("fal", "fal-ai/kling-video/v2/master/text-to-video")]
    assert kling.est_cost and kling.est_cost > 0


# --- Fal adapter -----------------------------------------------------------


def test_fal_provider_submit_poll_fetch():
    states = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Key fal-key"
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "req-9",
                    "status_url": "https://queue.fal.run/m/requests/req-9/status",
                    "response_url": "https://queue.fal.run/m/requests/req-9",
                },
            )
        if path.endswith("/status"):
            return httpx.Response(200, json={"status": next(states)})
        return httpx.Response(
            200,
            json={"video": {"url": "https://fal.media/out.mp4", "content_type": "video/mp4"}},
        )

    provider = FalProvider(
        "fal-key", httpx.Client(transport=httpx.MockTransport(handler)), poll_interval_s=0
    )
    generation = Generation(
        provider="fal", model="fal-ai/kling-video/v2/master/text-to-video",
        kind=T2V, prompt="a whip pan across a market",
    )
    result = provider.generate(generation)
    assert result.download_url == "https://fal.media/out.mp4"
    assert result.external_id == "req-9"
    # No billed_cost in the response -> the roster estimate is recorded.
    assert result.cost == 1.40


def test_fal_provider_billed_cost_wins_over_estimate():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-2"})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(
            200,
            json={"video": {"url": "https://fal.media/o.mp4"}, "billed_cost": 0.91},
        )

    provider = FalProvider(
        "k", httpx.Client(transport=httpx.MockTransport(handler)), poll_interval_s=0
    )
    generation = Generation(
        provider="fal", model="fal-ai/kling-video/v2/master/text-to-video",
        kind=T2V, prompt="x",
    )
    assert provider.generate(generation).cost == 0.91


def test_fal_provider_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-1"})
        return httpx.Response(200, json={"status": "FAILED"})

    provider = FalProvider("k", httpx.Client(transport=httpx.MockTransport(handler)), poll_interval_s=0)
    generation = Generation(provider="fal", model="m", kind=T2V, prompt="x")
    with pytest.raises(RuntimeError, match="FAILED"):
        provider.generate(generation)


# --- ElevenLabs adapter ------------------------------------------------------


def _eleven(handler) -> "ElevenLabsProvider":
    from pipeline_core.providers import ElevenLabsProvider

    return ElevenLabsProvider("xi-key", httpx.Client(transport=httpx.MockTransport(handler)))


def test_registry_gates_elevenlabs_on_key():
    assert "elevenlabs" not in build_registry(Settings(elevenlabs_api_key="", _env_file=None)).providers
    registry = build_registry(Settings(elevenlabs_api_key="k", _env_file=None))
    assert "elevenlabs" in registry.providers
    # API class -> cpu-lane network jobs, never the GPU lock
    assert all(s.provider_class == "api" for s in registry.providers["elevenlabs"].models())


def test_elevenlabs_tts_sends_key_and_returns_audio():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("xi-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"mp3-bytes", headers={"content-type": "audio/mpeg"})

    generation = Generation(
        provider="elevenlabs", model="eleven-tts", kind=GenerationKind.voice,
        prompt="welcome back", params={"voice_id": "voice-42"},
    )
    result = _eleven(handler).generate(generation)
    assert result.data == b"mp3-bytes"
    assert result.content_type == "audio/mpeg"
    assert result.cost == 0.15
    assert seen["key"] == "xi-key"
    assert seen["path"].endswith("/text-to-speech/voice-42")
    assert seen["body"]["text"] == "welcome back"


def test_elevenlabs_sfx_clamps_duration_to_api_cap():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"sfx", headers={"content-type": "audio/mpeg"})

    generation = Generation(
        provider="elevenlabs", model="eleven-sfx", kind=GenerationKind.music,
        prompt="glass shattering", params={"duration_s": 120},
    )
    _eleven(handler).generate(generation)
    assert seen["body"]["duration_seconds"] == 22.0


def test_elevenlabs_music_takes_duration_in_ms():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"song", headers={"content-type": "audio/mpeg"})

    generation = Generation(
        provider="elevenlabs", model="eleven-music", kind=GenerationKind.music,
        prompt="upbeat synthwave", params={"duration_s": 45},
    )
    result = _eleven(handler).generate(generation)
    assert seen["body"]["music_length_ms"] == 45_000
    assert result.cost == 0.50


def test_voiceover_route_via_elevenlabs_runs_on_cpu_lane(client, dispatcher):
    from pipeline_core.providers import ElevenLabsProvider

    registry = ProviderRegistry()
    registry.register(LocalWanProvider())
    registry.register(ElevenLabsProvider("k", httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500)))))
    client.app.dependency_overrides[get_registry] = lambda: registry

    response = client.post("/music/voice", json={
        "text": "an api-voiced line", "provider": "elevenlabs", "model": "eleven-tts",
        "voice_id": "voice-9",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["params"]["voice_id"] == "voice-9"
    # ToS provenance recorded on the asset licence (roadmap §3 rule)
    assert "ElevenLabs" in body["params"]["asset_license"]
    queue, _, _, _ = dispatcher.calls[-1]
    assert queue == "cpu"  # network job — never the GPU lock
