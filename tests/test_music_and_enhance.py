"""M18 acceptance: music generation lands as a licensed-clean library asset
(shared GPU lane — never the wan lock, never the cpu lane for local models);
a prompt-enhanced generation records both raw and enhanced prompts."""

from __future__ import annotations

import uuid

from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
from api.routes.generations import get_registry
from pipeline_core.enhance import HeuristicEnhancer, apply_enhancement
from pipeline_core.generation import STAGE_SHARED, run_generation
from pipeline_core.providers import (
    CLASS_API,
    LANE_SHARED,
    ModelSpec,
    ProviderRegistry,
    ProviderResult,
    build_registry,
)
from pipeline_core.queues import QUEUE_GPU
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, Generation, GenerationKind


class FakeMusicProvider:
    name = "local"
    provider_class = CLASS_API  # runs on cpu in tests — no GPU lock needed

    def models(self):
        return [ModelSpec(self.name, "ace-step", frozenset({GenerationKind.music}), CLASS_API)]

    def generate(self, generation):
        return ProviderResult(data=b"mp3-bytes", content_type="audio/mpeg", external_id="m-1")


# --- lane routing ------------------------------------------------------------


def test_ace_step_registered_on_shared_lane():
    specs = {s.model: s for s in build_registry(Settings()).catalog() if s.provider == "local"}
    assert specs["ace-step"].lane == LANE_SHARED
    assert GenerationKind.music in specs["ace-step"].kinds
    # the 14B-class models stay on the exclusive wan lane
    assert specs["wan2.2-vace-fun"].lane == "wan"


def test_music_generation_routes_to_shared_gpu_lane(client, dispatcher):
    """With the real registry, a local music job rides the render queue via
    generation_stage_shared — never the wan lock, never the cpu lane."""
    response = client.post("/music/generate", json={"prompt": "warm lofi beat"})
    assert response.status_code == 201, response.text
    queue, func_path, args, _ = dispatcher.calls[-1]
    assert queue == QUEUE_GPU
    assert func_path == STAGE_SHARED
    assert args == (response.json()["id"],)


# --- licensed-clean asset ----------------------------------------------------


def test_music_lands_as_licensed_clean_asset(client, engine, dispatcher, monkeypatch):
    registry = ProviderRegistry()
    registry.register(FakeMusicProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry

    response = client.post(
        "/music/generate", json={"prompt": "cinematic swelling strings", "duration_s": 45}
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["kind"] == "music"
    assert generation["params"]["duration_s"] == 45
    assert "Apache 2.0" in generation["params"]["asset_license"]

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="music-test"))
        store.ensure_bucket()
        run_generation(generation["id"], registry=registry, store=store)

    with Session(engine) as session:
        row = session.get(Generation, uuid.UUID(generation["id"]))
        asset = session.get(Asset, row.asset_id)
        assert asset.origin == AssetOrigin.generated
        assert asset.uri.endswith(".mp3")
        assert "Apache 2.0" in asset.license  # licence provenance recorded
        assert asset.approved is False


def test_music_validates_model_and_project(client):
    unknown = client.post(
        "/music/generate", json={"prompt": "x y", "model": "musicgen"}  # rejected licence
    )
    assert unknown.status_code == 422
    missing = client.post(
        "/music/generate", json={"prompt": "x y", "project_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 404


# --- prompt enhancement ------------------------------------------------------


def test_heuristic_enhancer_is_deterministic_and_idempotent():
    enhancer = HeuristicEnhancer()
    once = enhancer.enhance("a fox in the snow")
    assert "a fox in the snow" in once and "cinematic lighting" in once
    assert enhancer.enhance(once) == once  # no suffix stacking


def test_enhanced_generation_records_both_prompts(client, dispatcher):
    response = client.post(
        "/generations",
        json={
            "provider": "local", "model": "wan2.2-t2v", "kind": "text_to_video",
            "prompt": "a fox in the snow", "enhance": True,
        },
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["params"]["prompt_raw"] == "a fox in the snow"
    assert generation["prompt"] != "a fox in the snow"
    assert "a fox in the snow" in generation["prompt"]
    assert generation["params"]["enhancer"] == "heuristic"


def test_unenhanced_generation_records_no_raw_prompt(client, dispatcher):
    response = client.post(
        "/generations",
        json={
            "provider": "local", "model": "wan2.2-t2v", "kind": "text_to_video",
            "prompt": "plain prompt here",
        },
    )
    assert response.status_code == 201
    params = response.json()["params"] or {}
    assert "prompt_raw" not in params


def test_apply_enhancement_preserves_existing_params():
    prompt, params = apply_enhancement("a fox", {"seed": 7})
    assert params["seed"] == 7
    assert params["prompt_raw"] == "a fox"
    assert prompt.startswith("a fox")


# --- Ollama enhancer backend -------------------------------------------------


def test_ollama_enhancer_uses_chat_response(monkeypatch):
    from pipeline_core.enhance import OllamaEnhancer

    seen = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "  a vivid rewritten prompt  "}}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["body"] = json
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    enhancer = OllamaEnhancer("http://ollama-host:11434/", "qwen3:4b")
    assert enhancer.enhance("a cat") == "a vivid rewritten prompt"
    assert seen["url"] == "http://ollama-host:11434/api/chat"
    assert seen["body"]["model"] == "qwen3:4b"
    assert seen["body"]["stream"] is False
    assert seen["body"]["messages"][1]["content"] == "a cat"


def test_ollama_enhancer_degrades_to_heuristic_on_error(monkeypatch):
    from pipeline_core.enhance import HeuristicEnhancer, OllamaEnhancer

    def boom(*args, **kwargs):
        raise ConnectionError("server stopped")

    monkeypatch.setattr("httpx.post", boom)
    enhancer = OllamaEnhancer("http://127.0.0.1:11434", "qwen3:4b")
    # a stopped Ollama must never break a generation request
    assert enhancer.enhance("a cat") == HeuristicEnhancer().enhance("a cat")


def test_get_enhancer_prefers_configured_ollama(monkeypatch):
    import pipeline_core.enhance as enhance

    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(enhance, "_enhancer", None)
    assert enhance.get_enhancer().name == "ollama"
    # reset so other tests get the default heuristic
    enhance._enhancer = None


def test_config_reports_ollama_flags(client, monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    body = client.get("/config").json()
    assert body["ollama_configured"] is False
    assert body["ollama_online"] is False

    monkeypatch.setenv("OLLAMA_URL", "http://ollama-host:11434")

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr("httpx.get", lambda url, timeout: FakeResponse())
    body = client.get("/config").json()
    assert body["ollama_configured"] is True
    assert body["ollama_online"] is True
