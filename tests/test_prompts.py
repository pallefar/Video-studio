"""M27 prompt intelligence: catalog registry audit, saved-prompt CRUD,
reverse prompt engineering from captions, and the upgraded structure-frame
enhancer."""

from __future__ import annotations

import uuid

from pipeline_core.enhance import QUALITY_SUFFIX, STRUCTURE_SUFFIX, HeuristicEnhancer
from pipeline_core.prompts import CATALOG, CATEGORIES, catalog, get_template
from schema.models import Asset, AssetOrigin


# --- registry audit ----------------------------------------------------------


def test_catalog_entries_are_complete():
    ids = [e.id for e in CATALOG]
    assert len(ids) == len(set(ids)), "duplicate template ids"
    assert len(CATALOG) >= 25
    for entry in CATALOG:
        assert entry.title and entry.template, entry.id
        assert entry.category in CATEGORIES, entry.id
        assert entry.kind in ("video", "image", "music", "any"), entry.id
        # techniques distilled from published guides carry their attribution
        if entry.category in ("structure", "camera", "motion", "lighting",
                              "style", "composition", "negative"):
            assert entry.source_url or entry.notes, f"{entry.id} lacks attribution"


def test_structure_templates_carry_subject_slot():
    for entry in catalog(category="structure"):
        assert "{subject}" in entry.template, entry.id


def test_standard_negatives_exist_per_kind():
    kinds = {e.kind for e in catalog(category="negative")}
    assert {"video", "image"} <= kinds


def test_catalog_filters():
    assert all(e.category == "camera" for e in catalog(category="camera"))
    music = catalog(kind="music")
    assert music and all(e.kind in ("music", "any") for e in music)
    assert get_template("wan-shot-frame").category == "structure"


# --- API: catalog + saved prompts -------------------------------------------


def test_catalog_route_filters(client):
    body = client.get("/prompts/catalog").json()
    assert set(body["categories"]) == set(CATEGORIES)
    cameras = client.get("/prompts/catalog?category=camera").json()["entries"]
    assert cameras and all(e["category"] == "camera" for e in cameras)


def test_saved_prompt_crud_roundtrip(client):
    created = client.post("/prompts", json={
        "title": "Neon chase", "text": "a neon-lit chase through rain",
        "kind": "video", "negative": "flicker", "tags": ["chase"],
    })
    assert created.status_code == 201, created.text
    prompt_id = created.json()["id"]

    listed = client.get("/prompts").json()
    assert [p["id"] for p in listed] == [prompt_id]
    assert listed[0]["source"] == "manual"

    assert client.delete(f"/prompts/{prompt_id}").status_code == 204
    assert client.get("/prompts").json() == []
    assert client.delete(f"/prompts/{prompt_id}").status_code == 404


# --- reverse prompt engineering ---------------------------------------------


def _asset(session, caption, uri="s3://b/clip.mp4"):
    asset = Asset(origin=AssetOrigin.generated, uri=uri, caption=caption,
                  has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def test_reverse_prompt_from_real_caption(client, session):
    asset = _asset(session, "a red vintage car parked on a rainy neon street")
    body = client.post(f"/prompts/reverse/{asset.id}").json()
    assert body["caption"] == asset.caption
    assert "red vintage car" in body["prompt"]
    assert QUALITY_SUFFIX in body["prompt"]  # enhanced, not just echoed
    assert "morphing" in body["negative_prompt"]  # standard video negative
    assert body["kind"] == "video"
    assert client.get("/prompts").json() == []  # save=false by default


def test_reverse_prompt_image_gets_image_negative(client, session):
    asset = _asset(session, "portrait of a violinist in golden light",
                   uri="s3://b/still.png")
    body = client.post(f"/prompts/reverse/{asset.id}").json()
    assert body["kind"] == "image"
    assert "lowres" in body["negative_prompt"]


def test_reverse_prompt_refuses_placeholder_caption(client, session):
    asset = _asset(session, "IMG_2041.mp4")
    response = client.post(f"/prompts/reverse/{asset.id}")
    assert response.status_code == 409
    assert "caption" in response.json()["detail"]


def test_reverse_prompt_save_files_it(client, session):
    asset = _asset(session, "a drone shot over a mountain lake at dawn")
    body = client.post(f"/prompts/reverse/{asset.id}?save=true").json()
    assert "saved_id" in body
    saved = client.get("/prompts").json()
    assert len(saved) == 1
    assert saved[0]["source"] == "reverse"
    assert saved[0]["asset_id"] == str(asset.id)


def test_reverse_prompt_unknown_asset_404s(client):
    assert client.post(f"/prompts/reverse/{uuid.uuid4()}").status_code == 404


# --- enhancer structure frame (E4) ------------------------------------------


def test_enhancer_adds_structure_frame_when_no_camera_language():
    enhanced = HeuristicEnhancer().enhance("a lighthouse in a storm")
    assert STRUCTURE_SUFFIX in enhanced
    assert QUALITY_SUFFIX in enhanced


def test_enhancer_respects_existing_camera_language():
    enhanced = HeuristicEnhancer().enhance("the camera orbits a lighthouse")
    assert STRUCTURE_SUFFIX not in enhanced  # user already directed the camera
    assert QUALITY_SUFFIX in enhanced


def test_enhancer_is_idempotent():
    enhancer = HeuristicEnhancer()
    once = enhancer.enhance("a lighthouse in a storm")
    assert enhancer.enhance(once) == once


# --- MCP exposure ------------------------------------------------------------


def test_mcp_gains_prompt_tools(client):
    import asyncio

    from studio_mcp.server import build_server

    server = build_server(client)
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert {"prompt_catalog", "reverse_prompt", "save_prompt", "list_saved_prompts"} <= tools
