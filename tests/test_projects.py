"""M20: projects as the container — asset center feeds video center; assets
are shared across projects and downloadable for social use."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
from api.routes.generations import get_registry
from pipeline_core.generation import run_generation
from pipeline_core.providers import ProviderRegistry
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, ProjectAsset
from tests.test_providers import FakeApiProvider


def _project(client, title="Q3 launch") -> dict:
    response = client.post("/projects", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _asset(session: Session, caption="clip") -> Asset:
    asset = Asset(origin=AssetOrigin.own, uri=f"s3://avatar-pipeline/{caption}.mp4",
                  caption=caption, has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


# --- CRUD + sharing --------------------------------------------------------


def test_project_crud(client):
    project = _project(client)
    assert project["asset_count"] == 0
    assert client.get(f"/projects/{project['id']}").json()["title"] == "Q3 launch"
    assert len(client.get("/projects").json()) == 1


def test_asset_shared_across_projects(client, session):
    a = _project(client, "Project A")
    b = _project(client, "Project B")
    asset = _asset(session)

    assert client.post(f"/projects/{a['id']}/assets/{asset.id}").status_code == 201
    assert client.post(f"/projects/{b['id']}/assets/{asset.id}").status_code == 201

    ids_a = [x["id"] for x in client.get(f"/projects/{a['id']}/assets").json()]
    ids_b = [x["id"] for x in client.get(f"/projects/{b['id']}/assets").json()]
    assert str(asset.id) in ids_a and str(asset.id) in ids_b

    # detaching from A leaves it in B and in the global library
    client.request("DELETE", f"/projects/{a['id']}/assets/{asset.id}")
    assert client.get(f"/projects/{a['id']}/assets").json() == []
    assert str(asset.id) in [x["id"] for x in client.get(f"/projects/{b['id']}/assets").json()]
    assert str(asset.id) in [x["id"] for x in client.get("/assets").json()]


def test_attach_is_idempotent_and_validates(client, session):
    project = _project(client)
    asset = _asset(session)
    client.post(f"/projects/{project['id']}/assets/{asset.id}")
    client.post(f"/projects/{project['id']}/assets/{asset.id}")  # second attach: no dup
    assert len(client.get(f"/projects/{project['id']}/assets").json()) == 1
    assert client.post(f"/projects/{project['id']}/assets/{uuid.uuid4()}").status_code == 404


# --- Generation flows into the project asset pool --------------------------


def test_preset_generation_lands_in_project(client, engine, dispatcher, monkeypatch):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    project = _project(client)

    response = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["zoom_in"],
            "subject": "a product box on a table",
            "provider": "fake",
            "model": "fake-t2v",
            "project_id": project["id"],
        },
    )
    assert response.status_code == 201, response.text
    generation = response.json()
    assert generation["project_id"] == project["id"]

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="proj-test"))
        store.ensure_bucket()
        run_generation(generation["id"], registry=registry, store=store)

    linked = client.get(f"/projects/{project['id']}/assets").json()
    assert len(linked) == 1
    assert linked[0]["origin"] == "generated"

    with Session(engine) as session:
        links = session.exec(select(ProjectAsset)).all()
        assert len(links) == 1


def test_generation_rejects_unknown_project(client):
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    response = client.post(
        "/presets/generate",
        json={
            "preset_ids": ["zoom_in"],
            "subject": "x y",
            "provider": "fake",
            "model": "fake-t2v",
            "project_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


# --- Storyboards live inside projects; shots can use pooled assets ----------


def test_storyboards_scoped_to_project(client):
    a = _project(client, "Project A")
    b = _project(client, "Project B")
    client.post("/storyboards", json={"title": "A video", "project_id": a["id"]})
    client.post("/storyboards", json={"title": "B video", "project_id": b["id"]})
    client.post("/storyboards", json={"title": "Unscoped"})

    titles_a = [s["title"] for s in client.get(f"/storyboards?project_id={a['id']}").json()]
    assert titles_a == ["A video"]
    assert len(client.get("/storyboards").json()) == 3

    missing = client.post("/storyboards", json={"title": "x y", "project_id": str(uuid.uuid4())})
    assert missing.status_code == 404


def test_shot_from_existing_asset_and_export(client, session, dispatcher):
    project = _project(client)
    asset = _asset(session, caption="reusable-broll")
    client.post(f"/projects/{project['id']}/assets/{asset.id}")
    board = client.post(
        "/storyboards", json={"title": "From pool", "project_id": project["id"]}
    ).json()

    response = client.post(
        f"/storyboards/{board['id']}/shots",
        json={"idx": 0, "subject": "pooled b-roll", "preset_ids": [], "asset_id": str(asset.id)},
    )
    assert response.status_code == 201, response.text
    shot = response.json()["shots"][0]
    assert shot["asset_id"] == str(asset.id)

    # a fixed-asset shot has nothing to generate
    generate = client.post(f"/storyboards/{board['id']}/shots/{shot['id']}/generate", json={})
    assert generate.status_code == 422

    # and the board is immediately exportable
    export = client.post(f"/storyboards/{board['id']}/export")
    assert export.status_code == 202, export.text
    assert export.json()["timeline"]["shots"][0]["asset_uri"] == asset.uri


def test_shot_requires_presets_or_asset(client):
    board = client.post("/storyboards", json={"title": "x y"}).json()
    response = client.post(
        f"/storyboards/{board['id']}/shots",
        json={"idx": 0, "subject": "empty", "preset_ids": []},
    )
    assert response.status_code == 422


# --- Social/download path --------------------------------------------------


def test_asset_download_presigned_url(client, session):
    from api.routes.assets import get_object_store

    with mock_aws():
        settings = Settings(s3_endpoint="", s3_bucket="avatar-pipeline")
        store = ObjectStore(settings)
        store.ensure_bucket()
        store.put_bytes("social/clip.mp4", b"bytes")
        asset = Asset(origin=AssetOrigin.generated, uri="s3://avatar-pipeline/social/clip.mp4",
                      caption="social clip", has_identifiable_people=False, approved=False)
        session.add(asset)
        session.commit()
        session.refresh(asset)

        client.app.dependency_overrides[get_object_store] = lambda: store
        response = client.get(f"/assets/{asset.id}/download")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "social/clip.mp4" in body["url"]
        assert body["uri"] == asset.uri
