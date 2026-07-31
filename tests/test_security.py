"""Production-hardening guarantees: infrastructure ports stay loopback-only,
uploads are size-capped with sanitised suffixes, stock ingest treats its
client-relayed body as untrusted, and the built SPA serves from the API
without shadowing routes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import api.routes.assets as assets_route
import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset

REPO = Path(__file__).resolve().parent.parent


# --- Infrastructure exposure -------------------------------------------------


def test_compose_ports_are_loopback_only():
    """The compose services carry default dev credentials and no TLS — a
    port published on 0.0.0.0 hands Postgres/Redis/MinIO to the whole LAN."""
    compose = (REPO / "docker-compose.yml").read_text()
    for match in re.finditer(r'-\s*"([^"]+)"', compose):
        mapping = match.group(1)
        if ":" not in mapping:
            continue
        assert mapping.startswith("127.0.0.1:"), (
            f"compose port {mapping!r} is not bound to loopback"
        )


def test_launchers_bind_api_to_loopback():
    for script in ("scripts/dev_up.sh", "scripts/start.ps1"):
        text = (REPO / script).read_text()
        assert "uvicorn" in text and "127.0.0.1" in text, script
        assert "--host 0.0.0.0" not in text and '"0.0.0.0"' not in text, script


# --- Upload hardening --------------------------------------------------------


@pytest.fixture()
def upload_store(client):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="sec-uploads"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store
        yield store


def test_upload_sanitises_hostile_suffixes(client, upload_store):
    for filename, expected in [
        ("../../etc/passwd", ".bin"),          # no suffix at all -> .bin
        ("clip.MP4", ".mp4"),                  # case-normalised
        ("weird.mp4;rm -rf", ".bin"),          # shell metacharacters refused
        ("x.averylongsuffix", ".bin"),         # length-capped allowlist
    ]:
        response = client.post(
            "/assets/upload", files={"file": (filename, b"bytes", "video/mp4")}
        )
        assert response.status_code == 201, response.text
        uri = response.json()["uri"]
        assert uri.endswith(expected), f"{filename} -> {uri}"
        # the client filename itself never appears in the object key
        _, key = ObjectStore.parse_uri(uri)
        assert key.startswith("assets/uploads/")
        assert "passwd" not in key and ";" not in key and ".." not in key


def test_upload_rejects_oversize(client, upload_store, monkeypatch):
    monkeypatch.setattr(assets_route, "MAX_UPLOAD_MB", 0)
    response = client.post(
        "/assets/upload", files={"file": ("big.mp4", b"x" * 1024, "video/mp4")}
    )
    assert response.status_code == 413


# --- Stock ingest treats the relayed body as untrusted -----------------------


@pytest.fixture()
def stock_env(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.setattr(cpu_stages, "download", lambda url: b"stock-bytes")
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="sec-stock"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda *a, **k: store)
        yield {"engine": engine, "store": store}


def _stock_body(**overrides) -> dict:
    body = {
        "provider": "pexels",
        "external_id": "12345",
        "kind": "video",
        "caption": "city aerial",
        "download_url": "https://media.example.com/clip.mp4",
        "preview_url": "https://media.example.com/thumb.jpg",
        "source_url": "https://example.com/video/12345",
        "license": "Pexels License",
        "duration_ms": 5000,
    }
    body.update(overrides)
    return body


def test_stock_ingest_requires_https(stock_env):
    for url in ("http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://x/y"):
        with pytest.raises(ValueError, match="https"):
            cpu_stages.stock_ingest_stage(_stock_body(download_url=url))


def test_stock_ingest_sanitises_key_components(stock_env):
    cpu_stages.stock_ingest_stage(
        _stock_body(provider="../jobs", external_id="../../8f7c/tts/0")
    )
    keys = stock_env["store"].list_keys()
    assert len(keys) == 1
    assert keys[0].startswith("assets/stock/")
    assert ".." not in keys[0] and "//" not in keys[0]
    with Session(stock_env["engine"]) as session:
        asset = session.exec(select(Asset)).one()
        assert asset.uri.endswith(keys[0])


# --- Production SPA serving --------------------------------------------------


def test_api_routes_win_over_spa_mount(client):
    # the mount (when web/dist is built) must never shadow API routes
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/stats").status_code == 200


@pytest.mark.skipif(not (REPO / "web" / "dist" / "index.html").exists(),
                    reason="panel not built in this environment")
def test_spa_serves_from_api_when_built():
    from fastapi.testclient import TestClient

    from api.main import create_app

    with TestClient(create_app()) as spa_client:
        response = spa_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
