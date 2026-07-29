"""M17 acceptance: identity LoRA training and face-bearing generation without
recorded consent are refused at the API layer (C6) — structural, like C1–C5.
Defence in depth: the wan-lane worker refuses too, so a raw enqueue around the
route cannot train an unconsented identity."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_gpu.stages as gpu_stages
from api.routes.generations import get_registry
from pipeline_core.providers import ProviderRegistry
from pipeline_core.queues import QUEUE_WAN
from schema.models import Asset, AssetOrigin, Identity, IdentityTrainingStatus
from tests.test_providers import FakeApiProvider


def _reference_asset(session: Session, caption="ref-photo") -> Asset:
    asset = Asset(origin=AssetOrigin.own, uri=f"s3://avatar-pipeline/refs/{caption}.jpg",
                  caption=caption, has_identifiable_people=True, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _identity(client, session: Session, name="owner", refs=1) -> dict:
    asset_ids = [str(_reference_asset(session, f"{name}-{i}").id) for i in range(refs)]
    response = client.post(
        "/identities", json={"name": name, "reference_asset_ids": asset_ids}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _consent(client, identity_id: str, recorded_by="karsten") -> dict:
    response = client.post(
        f"/identities/{identity_id}/consent", json={"recorded_by": recorded_by}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fake_registry(client) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


# --- entity -----------------------------------------------------------------


def test_identity_created_without_consent(client, session):
    identity = _identity(client, session)
    assert identity["has_consent"] is False
    assert identity["consent_recorded_by"] is None
    assert identity["training_status"] == "untrained"
    assert [identity["id"]] == [i["id"] for i in client.get("/identities").json()]


def test_identity_name_unique_and_refs_validated(client, session):
    _identity(client, session, name="owner")
    dup = client.post("/identities", json={"name": "owner", "reference_asset_ids": []})
    assert dup.status_code == 409
    missing_ref = client.post(
        "/identities", json={"name": "other", "reference_asset_ids": [str(uuid.uuid4())]}
    )
    assert missing_ref.status_code == 404


# --- consent recording ------------------------------------------------------


def test_consent_recorded_once_then_immutable(client, session):
    identity = _identity(client, session)
    consented = _consent(client, identity["id"])
    assert consented["has_consent"] is True
    assert consented["consent_recorded_by"] == "karsten"
    assert consented["consent_at"] is not None

    again = client.post(f"/identities/{identity['id']}/consent", json={"recorded_by": "someone"})
    assert again.status_code == 409


def test_consent_requires_recorder_name(client, session):
    identity = _identity(client, session)
    blank = client.post(f"/identities/{identity['id']}/consent", json={"recorded_by": "   "})
    assert blank.status_code == 422


# --- C6: training refused without consent ------------------------------------


def test_training_refused_without_consent(client, session, dispatcher):
    identity = _identity(client, session)
    response = client.post(f"/identities/{identity['id']}/train")
    assert response.status_code == 422
    assert "C6" in response.json()["detail"]
    assert dispatcher.calls == []  # nothing reached the wan queue


def test_training_enqueues_on_wan_lane_with_consent(client, session, dispatcher):
    identity = _identity(client, session)
    _consent(client, identity["id"])
    response = client.post(f"/identities/{identity['id']}/train")
    assert response.status_code == 202, response.text
    assert response.json()["training_status"] == "queued"

    (queue, func_path, args, job_key), = dispatcher.calls
    assert queue == QUEUE_WAN  # exclusive GPU lock lane, never the render lane
    assert func_path == "worker_gpu.stages.identity_training_stage"
    assert args == (identity["id"],)
    assert job_key == f"identity-train-{identity['id']}"

    # double-submit while queued is refused
    assert client.post(f"/identities/{identity['id']}/train").status_code == 409


def test_training_requires_reference_assets(client, session):
    identity = _identity(client, session, name="no-refs", refs=0)
    _consent(client, identity["id"])
    response = client.post(f"/identities/{identity['id']}/train")
    assert response.status_code == 422
    assert "reference" in response.json()["detail"]


# --- C6: face-bearing generation refused without consent ---------------------


def test_generation_with_unconsented_identity_refused(client, session):
    _fake_registry(client)
    identity = _identity(client, session)
    response = client.post(
        "/generations",
        json={
            "provider": "fake", "model": "fake-t2v", "kind": "text_to_video",
            "prompt": "the owner walking on a beach", "identity_id": identity["id"],
        },
    )
    assert response.status_code == 422
    assert "C6" in response.json()["detail"]


def test_preset_generation_with_unconsented_identity_refused(client, session):
    _fake_registry(client)
    identity = _identity(client, session)
    response = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["zoom_in"], "subject": "the owner at a desk",
            "provider": "fake", "model": "fake-t2v", "identity_id": identity["id"],
        },
    )
    assert response.status_code == 422
    assert "C6" in response.json()["detail"]


def test_generation_with_consented_identity_links_and_carries_lora(client, session):
    _fake_registry(client)
    identity = _identity(client, session)
    _consent(client, identity["id"])

    # a trained identity carries its LoRA into the generation params
    row = session.get(Identity, uuid.UUID(identity["id"]))
    row.training_status = IdentityTrainingStatus.trained
    row.lora_uri = "s3://avatar-pipeline/identities/x/lora.safetensors"
    session.add(row)
    session.commit()

    response = client.post(
        "/generations",
        json={
            "provider": "fake", "model": "fake-t2v", "kind": "text_to_video",
            "prompt": "the owner walking on a beach", "identity_id": identity["id"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["identity_id"] == identity["id"]
    assert body["params"]["identity_lora_uri"] == row.lora_uri


def test_generation_with_unknown_identity_404(client):
    _fake_registry(client)
    response = client.post(
        "/generations",
        json={
            "provider": "fake", "model": "fake-t2v", "kind": "text_to_video",
            "prompt": "x y", "identity_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


# --- defence in depth: the worker refuses too --------------------------------


def test_worker_refuses_unconsented_identity(engine, session, monkeypatch):
    """A raw enqueue around the API gate still cannot train: the wan-lane
    stage re-checks consent before it ever touches the GPU lock."""
    identity = Identity(name="bypassed", reference_asset_ids=[])
    session.add(identity)
    session.commit()
    session.refresh(identity)

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with pytest.raises(ValueError, match="C6"):
        gpu_stages.identity_training_stage(str(identity.id))

    session.refresh(identity)
    assert identity.training_status == IdentityTrainingStatus.failed
    assert "consent" in identity.error


def test_worker_trains_consented_identity(engine, session, monkeypatch, redis_url):
    """Happy path under the real wan-lane lock: consented identity trains,
    lands its LoRA uri, and ends trained."""
    from redis import Redis

    from schema.models import utcnow

    identity = Identity(
        name="consented",
        reference_asset_ids=[str(uuid.uuid4())],
        consent_recorded_by="karsten",
        consent_at=utcnow(),
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)

    class FakeTrainer:
        def train(self, identity_id, reference_asset_ids):
            return f"s3://avatar-pipeline/identities/{identity_id}/lora.safetensors"

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setattr(gpu_stages, "_trainer", FakeTrainer())
    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **k: Redis.from_url(redis_url))

    gpu_stages.identity_training_stage(str(identity.id))

    session.refresh(identity)
    assert identity.training_status == IdentityTrainingStatus.trained
    assert identity.lora_uri.endswith("lora.safetensors")
    assert identity.error is None

    # idempotent: a replayed job is a no-op, not a retrain
    gpu_stages.identity_training_stage(str(identity.id))
