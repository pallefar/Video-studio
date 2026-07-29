"""M13 acceptance: an effect preset applied to an existing library asset
produces a NEW derived asset with a provenance chain back to the source.
Also: the Mix mechanic (effects + camera presets), the fast-preview path,
and the upscale finishing lane."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
from api.routes.generations import get_registry
from pipeline_core.effects import EffectError, compose_mix, validate_effect_stack
from pipeline_core.generation import run_generation
from pipeline_core.providers import CLASS_API, ModelSpec, ProviderRegistry, ProviderResult, build_registry
from pipeline_core.queues import QUEUE_CPU, QUEUE_WAN
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, Generation, GenerationKind


class FakeVfxProvider:
    """'local' name so route defaults resolve; API class so tests run the
    cpu lane without a GPU lock."""

    name = "local"
    provider_class = CLASS_API

    def models(self):
        v2v = frozenset({GenerationKind.video_to_video})
        upscale = frozenset({GenerationKind.upscale})
        return [
            ModelSpec(self.name, "wan2.2-vace-fun", v2v, CLASS_API),
            ModelSpec(self.name, "wan2.1-vace-1.3b", v2v, CLASS_API),
            ModelSpec(self.name, "seedvr2-3b", upscale, CLASS_API),
        ]

    def generate(self, generation):
        return ProviderResult(data=b"restyled-bytes", external_id="vfx-1")


def _fake_registry(client) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeVfxProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


def _source_asset(session: Session, caption="drone shot") -> Asset:
    asset = Asset(origin=AssetOrigin.own, uri=f"s3://avatar-pipeline/own/{uuid.uuid4()}.mp4",
                  caption=caption, has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


# --- registry + composition --------------------------------------------------


def test_effect_stack_validation():
    assert [e.id for e in validate_effect_stack(["levitation", "glitch"])] == ["levitation", "glitch"]
    with pytest.raises(EffectError):
        validate_effect_stack([])
    with pytest.raises(EffectError):
        validate_effect_stack(["levitation", "levitation"])
    with pytest.raises(EffectError):
        validate_effect_stack(["nope"])
    with pytest.raises(EffectError):
        validate_effect_stack(["restyle_anime", "glitch"])  # restyles don't stack


def test_mix_composes_effects_and_camera(client):
    prompt, params = compose_mix(["levitation"], ["orbit_360"])
    assert "levitates" in prompt and "orbits 360 degrees around the scene" in prompt
    assert params["effects"] == ["levitation"]
    assert params["motion_codes"] == ["Pan Left"]

    with pytest.raises(EffectError):
        compose_mix(["levitation"], ["not-a-camera"])


def test_effects_endpoint_lists_registry(client):
    effects = client.get("/effects").json()
    assert {"levitation", "restyle_anime"} <= {e["id"] for e in effects}


def test_vace_models_in_local_catalog():
    catalog = {spec.model for spec in build_registry(Settings()).catalog() if spec.provider == "local"}
    assert {"wan2.2-vace-fun", "wan2.1-vace-1.3b", "seedvr2-3b", "real-esrgan", "film"} <= catalog


# --- apply -> derived asset with provenance ----------------------------------


def test_effect_apply_derives_asset_with_provenance(client, session, engine, dispatcher, monkeypatch):
    registry = _fake_registry(client)
    source = _source_asset(session)

    response = client.post(
        "/effects/apply",
        json={"asset_id": str(source.id), "effect_ids": ["set_on_fire"],
              "camera_preset_ids": ["crash_zoom_in"]},
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["kind"] == "video_to_video"
    assert generation["model"] == "wan2.2-vace-fun"
    assert generation["source_asset_id"] == str(source.id)
    assert generation["params"]["source_asset_uri"] == source.uri
    assert generation["params"]["effects"] == ["set_on_fire"]

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="vfx-test"))
        store.ensure_bucket()
        run_generation(generation["id"], registry=registry, store=store)

    with Session(engine) as session2:
        row = session2.get(Generation, uuid.UUID(generation["id"]))
        derived = session2.get(Asset, row.asset_id)
        assert derived.id != source.id  # the source is never touched
        assert derived.origin == AssetOrigin.generated

    chain = client.get(f"/assets/{derived.id}/provenance").json()
    assert len(chain) == 2
    assert chain[0]["asset"]["id"] == str(derived.id)
    assert chain[0]["generation"]["model"] == "wan2.2-vace-fun"
    assert chain[0]["generation"]["source_asset_id"] == str(source.id)
    assert chain[1]["asset"]["id"] == str(source.id)
    assert chain[1]["generation"] is None  # the original is the root


def test_preview_routes_to_fast_model(client, session, dispatcher):
    _fake_registry(client)
    source = _source_asset(session)
    generation = client.post(
        "/effects/apply",
        json={"asset_id": str(source.id), "effect_ids": ["glitch"], "preview": True},
    ).json()
    assert generation["model"] == "wan2.1-vace-1.3b"
    assert generation["params"]["preview"] is True


def test_local_vace_apply_runs_on_wan_lane(client, session, dispatcher):
    """With the real registry the VACE models are local: the job must take
    the wan queue (exclusive GPU lock lane), never the render lane."""
    source = _source_asset(session)
    response = client.post(
        "/effects/apply", json={"asset_id": str(source.id), "effect_ids": ["freeze"]}
    )
    assert response.status_code == 201, response.text
    assert dispatcher.calls[-1][0] == QUEUE_WAN


def test_apply_validates_inputs(client, session):
    _fake_registry(client)
    source = _source_asset(session)
    missing = client.post(
        "/effects/apply", json={"asset_id": str(uuid.uuid4()), "effect_ids": ["glitch"]}
    )
    assert missing.status_code == 404
    unknown = client.post(
        "/effects/apply", json={"asset_id": str(source.id), "effect_ids": ["sparkle-nope"]}
    )
    assert unknown.status_code == 422


# --- finishing lane ----------------------------------------------------------


def test_upscale_derives_with_provenance_link(client, session, dispatcher):
    _fake_registry(client)
    source = _source_asset(session, caption="hero shot")
    response = client.post("/effects/upscale", json={"asset_id": str(source.id)})
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["kind"] == "upscale"
    assert generation["model"] == "seedvr2-3b"
    assert generation["source_asset_id"] == str(source.id)
    assert generation["params"]["purpose"] == "finishing"
    assert dispatcher.calls[-1][0] == QUEUE_CPU  # fake is API-class -> network job
