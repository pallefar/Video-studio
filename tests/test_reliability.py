"""Phase B reliability: generation retry/cancel state machine, worker
liveness in /stats, and the /config route's booleans-only guarantee."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session

import pipeline_core.db as core_db
from api.routes.generations import get_registry
from pipeline_core.generation import run_generation
from pipeline_core.providers import CLASS_API, ModelSpec, ProviderRegistry
from schema.models import Generation, GenerationKind, GenerationStatus


class _FakeProvider:
    name = "fake"
    provider_class = CLASS_API

    def models(self):
        return [ModelSpec("fake", "fake-t2v", frozenset({GenerationKind.text_to_video}), CLASS_API)]

    def generate(self, generation):  # pragma: no cover - not exercised here
        raise AssertionError("not called")


@pytest.fixture()
def api_registry(client):
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


def _seed_generation(session: Session, status: GenerationStatus) -> Generation:
    generation = Generation(
        provider="fake", model="fake-t2v", kind=GenerationKind.text_to_video,
        prompt="a slow dolly through fog",
    )
    generation.status = status
    if status == GenerationStatus.failed:
        generation.error = "ProviderError: exploded"
    session.add(generation)
    session.commit()
    session.refresh(generation)
    return generation


# --- retry ------------------------------------------------------------------


def test_retry_requeues_failed_generation(client, session, api_registry, dispatcher):
    generation = _seed_generation(session, GenerationStatus.failed)
    response = client.post(f"/generations/{generation.id}/retry")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["error"] is None
    queue, func, args, _ = dispatcher.calls[-1]
    assert args == (str(generation.id),)


def test_retry_refuses_non_failed(client, session, api_registry):
    for status in (GenerationStatus.queued, GenerationStatus.running, GenerationStatus.succeeded):
        generation = _seed_generation(session, status)
        assert client.post(f"/generations/{generation.id}/retry").status_code == 409


# --- cancel -----------------------------------------------------------------


def test_cancel_queued_generation(client, session):
    generation = _seed_generation(session, GenerationStatus.queued)
    response = client.post(f"/generations/{generation.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_refuses_running(client, session):
    generation = _seed_generation(session, GenerationStatus.running)
    assert client.post(f"/generations/{generation.id}/cancel").status_code == 409


def test_worker_honours_cancellation(engine, monkeypatch):
    """The RQ job still fires for a cancelled generation — the stage must
    skip it instead of running the provider."""
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with Session(engine) as session:
        generation = _seed_generation(session, GenerationStatus.cancelled)
        generation_id = str(generation.id)

    class ExplodingProvider:
        provider_class = "api"

        def models(self):  # pragma: no cover - never called
            return []

        def generate(self, generation):  # pragma: no cover - must not run
            raise AssertionError("cancelled generation must never generate")

    registry = ProviderRegistry()
    registry.providers["fake"] = ExplodingProvider()
    run_generation(generation_id, registry=registry)

    with Session(engine) as session:
        assert (
            session.get(Generation, uuid.UUID(generation_id)).status
            == GenerationStatus.cancelled
        )


def test_unknown_generation_404s(client):
    assert client.post(f"/generations/{uuid.uuid4()}/retry").status_code == 404
    assert client.post(f"/generations/{uuid.uuid4()}/cancel").status_code == 404


# --- worker liveness in /stats ----------------------------------------------


def test_stats_health_block_degrades_without_redis(client, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # nothing there
    body = client.get("/stats").json()
    assert body["health"] == {"available": False, "workers": [], "queues": {}}


def test_stats_health_reports_queues_with_real_redis(client, redis_url, monkeypatch):
    monkeypatch.setenv("REDIS_URL", redis_url)
    health = client.get("/stats").json()["health"]
    assert health["available"] is True
    assert set(health["queues"]) == {"gpu", "cpu", "wan"}
    assert isinstance(health["workers"], list)


# --- /config never leaks a value --------------------------------------------


def test_config_reports_booleans_only(client, monkeypatch):
    monkeypatch.setenv("FAL_API_KEY", "sk-super-secret")
    monkeypatch.setenv("COMFY_URL", "http://gpu-host:8188")
    body = client.get("/config").json()
    assert body["fal_configured"] is True
    assert body["comfy_configured"] is True
    for key, value in body.items():
        assert isinstance(value, bool), f"{key} leaked a non-boolean value"
    assert "sk-super-secret" not in str(body)
    assert "gpu-host" not in str(body)
