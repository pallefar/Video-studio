"""Stock ingest: search endpoint → enqueued download → Asset row with full
provenance and the identifiable-people hold."""

from __future__ import annotations

import httpx
import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from api.routes.assets import get_stock_providers
from pipeline_core.settings import Settings
from pipeline_core.stock import PexelsProvider
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin
from tests.test_stock_providers import PEXELS_VIDEO_RESPONSE

RESULT_PAYLOAD = {
    "provider": "pexels",
    "external_id": "101",
    "kind": "video",
    "caption": "Hands typing on a keyboard in an office",
    "download_url": "https://videos.pexels.com/101/hd.mp4",
    "preview_url": "https://images.pexels.com/101/preview.jpg",
    "source_url": "https://www.pexels.com/video/office-101/",
    "license": "Pexels License",
    "duration_ms": 12000,
}


def test_search_endpoint_uses_injected_providers(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PEXELS_VIDEO_RESPONSE)

    provider = PexelsProvider("k", httpx.Client(transport=httpx.MockTransport(handler)))
    client.app.dependency_overrides[get_stock_providers] = lambda: [provider]

    response = client.get("/assets/stock/search", params={"query": "office keyboard"})
    assert response.status_code == 200, response.text
    results = response.json()
    assert len(results) == 1
    assert results[0]["license"] == "Pexels License"
    assert results[0]["source_url"]


def test_search_endpoint_503_without_providers(client):
    client.app.dependency_overrides[get_stock_providers] = lambda: []
    assert client.get("/assets/stock/search", params={"query": "office"}).status_code == 503


def test_ingest_endpoint_enqueues_cpu_job(client, dispatcher):
    response = client.post("/assets/stock/ingest", json=RESULT_PAYLOAD)
    assert response.status_code == 202, response.text
    assert len(dispatcher.calls) == 1
    queue_name, func_path, args, job_key = dispatcher.calls[0]
    assert queue_name == "cpu"
    assert func_path == "worker_cpu.stages.stock_ingest_stage"
    assert args[0]["license"] == "Pexels License"
    assert job_key == "stock-ingest-pexels-101"


def test_ingest_endpoint_rejects_missing_provenance(client):
    payload = dict(RESULT_PAYLOAD, license="")
    assert client.post("/assets/stock/ingest", json=payload).status_code == 422


def test_ingest_stage_downloads_and_creates_held_asset(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setattr(cpu_stages, "download", lambda url: b"fake-video-bytes")

    with mock_aws():
        settings = Settings(s3_endpoint="", s3_bucket="ingest-test")
        store = ObjectStore(settings)
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)

        asset_id = cpu_stages.stock_ingest_stage(RESULT_PAYLOAD)

        with Session(engine) as session:
            asset = session.exec(select(Asset)).one()
        assert str(asset.id) == asset_id
        assert asset.origin == AssetOrigin.stock
        assert asset.license == "Pexels License"
        assert asset.source_url == "https://www.pexels.com/video/office-101/"
        assert asset.has_identifiable_people is True  # held until a human clears it
        assert asset.approved is False
        assert asset.embedding and len(asset.embedding) > 0
        assert asset.uri == "s3://ingest-test/assets/stock/pexels/101.mp4"
        assert store.get_bytes("assets/stock/pexels/101.mp4") == b"fake-video-bytes"


def test_ingest_stage_requires_provenance(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with pytest.raises(ValueError, match="license"):
        cpu_stages.stock_ingest_stage(dict(RESULT_PAYLOAD, license=""))
