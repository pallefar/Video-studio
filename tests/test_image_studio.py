"""M12 acceptance: style preset -> image lands in the library; storyboard
mode produces N frames with recorded shared params; the thumbnail pipeline
targets 1280x720 on the text-capable model."""

from __future__ import annotations

import uuid

from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
from api.routes.generations import get_registry
from pipeline_core.generation import run_generation
from pipeline_core.providers import CLASS_API, ModelSpec, ProviderRegistry, ProviderResult, build_registry
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, GenerationKind, Identity, IdentityTrainingStatus, utcnow


class FakeImageProvider:
    """Registers under the 'local' name so the route defaults resolve, but as
    an API-class provider so tests run on the cpu lane without a GPU lock."""

    name = "local"
    provider_class = CLASS_API

    def models(self):
        image = frozenset({GenerationKind.image})
        return [
            ModelSpec(self.name, "z-image-turbo", image, CLASS_API),
            ModelSpec(self.name, "qwen-image", image, CLASS_API),
            ModelSpec(self.name, "sdxl", image, CLASS_API),
        ]

    def generate(self, generation):
        return ProviderResult(data=b"png-bytes", content_type="image/png", external_id="img-1")


def _fake_registry(client) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeImageProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


# --- registry ---------------------------------------------------------------


def test_image_models_in_local_catalog():
    catalog = {spec.model for spec in build_registry(Settings()).catalog() if spec.provider == "local"}
    assert {"z-image-turbo", "qwen-image", "sdxl"} <= catalog


# --- style preset -> image in the library ------------------------------------


def test_styled_image_lands_in_library(client, engine, dispatcher, monkeypatch):
    registry = _fake_registry(client)
    response = client.post(
        "/images/generate",
        json={"prompt": "a lighthouse at dusk", "style_id": "neon_night"},
    )
    assert response.status_code == 201, response.text
    (generation,) = response.json()
    assert "neon-lit night scene" in generation["prompt"]
    assert generation["params"]["style"] == "neon_night"
    # image-class fake runs as a network job on the cpu lane
    assert dispatcher.calls[0][0] == QUEUE_CPU

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="img-test"))
        store.ensure_bucket()
        run_generation(generation["id"], registry=registry, store=store)

    with Session(engine) as session:
        asset = session.exec(select(Asset)).one()
        assert asset.origin == AssetOrigin.generated
        assert asset.uri.endswith(".png")
        assert asset.approved is False


def test_unknown_style_refused(client):
    _fake_registry(client)
    response = client.post(
        "/images/generate", json={"prompt": "x y", "style_id": "vaporwave-nope"}
    )
    assert response.status_code == 422


# --- storyboard mode ---------------------------------------------------------


def test_storyboard_mode_shares_seed_and_style(client, dispatcher):
    _fake_registry(client)
    response = client.post(
        "/images/generate",
        json={"prompt": "detective enters the archive", "style_id": "film_16mm", "frames": 4},
    )
    assert response.status_code == 201, response.text
    frames = response.json()
    assert len(frames) == 4
    assert len(dispatcher.calls) == 4

    seeds = {f["params"]["seed"] for f in frames}
    styles = {f["params"]["style"] for f in frames}
    assert len(seeds) == 1, "storyboard frames must share one seed"
    assert styles == {"film_16mm"}
    assert [f["params"]["frame"] for f in frames] == [0, 1, 2, 3]
    assert all(f["params"]["frames"] == 4 for f in frames)


def test_pinned_seed_is_honoured(client):
    _fake_registry(client)
    response = client.post(
        "/images/generate", json={"prompt": "same take again", "seed": 421337, "frames": 2}
    )
    assert {f["params"]["seed"] for f in response.json()} == {421337}


def test_frame_count_capped(client):
    _fake_registry(client)
    response = client.post("/images/generate", json={"prompt": "x y", "frames": 10})
    assert response.status_code == 422


# --- thumbnail pipeline ------------------------------------------------------


def test_thumbnail_targets_youtube_resolution_and_text_model(client):
    _fake_registry(client)
    response = client.post("/images/thumbnail", json={"title": "Why your backlog is lying"})
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["model"] == "qwen-image"
    assert generation["params"]["width"] == 1280
    assert generation["params"]["height"] == 720
    assert generation["params"]["purpose"] == "thumbnail"
    assert "Why your backlog is lying" in generation["prompt"]


# --- gates carry over --------------------------------------------------------


def test_image_generation_respects_c6(client, session):
    _fake_registry(client)
    identity = Identity(name="unconsented", reference_asset_ids=[])
    session.add(identity)
    session.commit()
    session.refresh(identity)

    refused = client.post(
        "/images/generate",
        json={"prompt": "portrait of the owner", "identity_id": str(identity.id)},
    )
    assert refused.status_code == 422
    assert "C6" in refused.json()["detail"]

    identity.consent_recorded_by = "karsten"
    identity.consent_at = utcnow()
    identity.training_status = IdentityTrainingStatus.trained
    identity.lora_uri = "s3://avatar-pipeline/identities/x/lora.safetensors"
    session.add(identity)
    session.commit()

    allowed = client.post(
        "/images/generate",
        json={"prompt": "portrait of the owner", "identity_id": str(identity.id)},
    )
    assert allowed.status_code == 201
    (generation,) = allowed.json()
    assert generation["identity_id"] == str(identity.id)
    assert generation["params"]["identity_lora_uri"] == identity.lora_uri


def test_image_generation_rejects_unknown_project(client):
    _fake_registry(client)
    response = client.post(
        "/images/generate", json={"prompt": "x y", "project_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
