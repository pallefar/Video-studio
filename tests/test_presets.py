"""M11 acceptance: preset request -> generation record -> asset with
origin='generated'; a preset referencing an unaudited LoRA fails validation."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import pipeline_core.presets as presets_module
from api.routes.generations import get_registry
from pipeline_core.generation import run_generation
from pipeline_core.presets import (
    CAMERA_PRESETS,
    PresetError,
    compose,
    get_preset,
    validate_stack,
)
from pipeline_core.providers import ProviderRegistry
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    CameraPresetRead,
    Generation,
    GenerationStatus,
    LoraRef,
)
from tests.test_providers import FakeApiProvider


# --- Registry rules --------------------------------------------------------


def test_all_shipped_presets_are_clean():
    """Shipped presets must not carry unaudited LoRAs — audited-or-absent."""
    for preset in CAMERA_PRESETS:
        for lora in preset.loras:
            assert lora.license_audited, f"{preset.id} ships unaudited LoRA {lora.name}"
    assert len({p.id for p in CAMERA_PRESETS}) == len(CAMERA_PRESETS)


def test_unknown_preset_rejected():
    with pytest.raises(PresetError, match="unknown preset"):
        validate_stack(["does_not_exist"])


def test_stack_limits():
    with pytest.raises(PresetError):
        validate_stack([])
    with pytest.raises(PresetError, match="at most"):
        validate_stack(["zoom_in", "pan_left", "tilt_up", "crane_up"])
    with pytest.raises(PresetError, match="duplicate"):
        validate_stack(["zoom_in", "zoom_in"])


def test_unstackable_preset_must_be_solo():
    validate_stack(["bullet_time"])  # alone is fine
    with pytest.raises(PresetError, match="not stackable"):
        validate_stack(["bullet_time", "zoom_in"])


def test_unaudited_lora_fails_validation(monkeypatch):
    tainted = CameraPresetRead(
        id="tainted_orbit",
        label="Tainted Orbit",
        description="test",
        category="orbit",
        motion_code="Pan Left",
        prompt_template="orbit {subject}",
        loras=[LoraRef(name="orbit-lora", weights_uri="s3://w/orbit.safetensors",
                       license="unknown-civitai", license_audited=False)],
    )
    monkeypatch.setitem(presets_module._BY_ID, "tainted_orbit", tainted)
    with pytest.raises(PresetError, match="not audited"):
        validate_stack(["tainted_orbit"])


def test_compose_builds_prompt_and_camera_params():
    presets = validate_stack(["crash_zoom_in", "handheld"])
    prompt, params = compose(presets, "a coffee cup")
    assert "crash zoom" in prompt
    assert "a coffee cup" in prompt
    assert params["camera_motion"] == ["Zoom In", "Static"]
    assert params["presets"] == ["crash_zoom_in", "handheld"]


# --- API -------------------------------------------------------------------


def test_list_presets_endpoint(client):
    presets = client.get("/presets").json()
    assert len(presets) == len(CAMERA_PRESETS)
    assert {"id", "label", "category", "motion_code"} <= set(presets[0])


def _fake_registry(client):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


def test_generate_endpoint_golden_path(client, dispatcher):
    _fake_registry(client)
    response = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["orbit_360"],
            "subject": "a vintage typewriter",
            "provider": "fake",
            "model": "fake-t2v",
        },
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["status"] == "queued"
    assert "orbits 360 degrees" in generation["prompt"]
    assert "a vintage typewriter" in generation["prompt"]
    assert generation["params"]["presets"] == ["orbit_360"]
    assert dispatcher.calls[-1][0] == "cpu"  # fake provider is api class


def test_generate_endpoint_defaults_to_local_fun_camera(client, dispatcher):
    response = client.post(
        "/presets/generate",
        json={"preset_ids": ["dolly_in"], "subject": "a mountain cabin"},
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["provider"] == "local"
    assert generation["model"] == "wan2.2-fun-camera"
    assert dispatcher.calls[-1][0] == "wan"  # local class -> wan lane


def test_generate_endpoint_rejects_bad_stack(client):
    _fake_registry(client)
    bad = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["bullet_time", "zoom_in"],
            "subject": "x y",
            "provider": "fake",
            "model": "fake-t2v",
        },
    )
    assert bad.status_code == 422
    assert "not stackable" in bad.json()["detail"]


def test_generate_endpoint_rejects_unknown_model(client):
    _fake_registry(client)
    response = client.post(
        "/presets/generate",
        json={"preset_ids": ["zoom_in"], "subject": "x y", "provider": "nope", "model": "m"},
    )
    assert response.status_code == 422


# --- Acceptance: preset -> generation -> asset with origin='generated' -----


def test_preset_generation_lands_in_asset_library(client, engine, dispatcher, monkeypatch):
    registry = _fake_registry(client)
    response = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["fpv_drone", "hyperlapse"],
            "subject": "a neon-lit alley",
            "provider": "fake",
            "model": "fake-t2v",
        },
    )
    generation_id = response.json()["id"]

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="preset-test"))
        store.ensure_bucket()
        run_generation(generation_id, registry=registry, store=store)

    with Session(engine) as session:
        generation = session.get(Generation, uuid.UUID(generation_id))
        assert generation.status == GenerationStatus.succeeded
        asset = session.get(Asset, generation.asset_id)
        assert asset.origin == AssetOrigin.generated
        assert asset.approved is False
        assert "neon-lit alley" in asset.caption
