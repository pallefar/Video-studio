"""M15: timeline documents — validation, versioned persistence (the
acceptance round-trip), storyboard hand-off, media presigning, and export
through the compiler with trims + text overlays."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from pydantic import ValidationError
from sqlmodel import Session

from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    TextClip,
    TimelineClip,
    TimelineDocument,
)
from worker_cpu.ffmpeg.compiler import build_ffmpeg_args


def _clip(start=0, in_ms=0, out_ms=2000, asset_id=None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "asset_id": asset_id or str(uuid.uuid4()),
        "start_ms": start,
        "in_ms": in_ms,
        "out_ms": out_ms,
    }


def _seed_asset(session: Session, caption="clip", origin=AssetOrigin.own) -> Asset:
    asset = Asset(origin=origin, uri=f"s3://avatar-pipeline/{uuid.uuid4()}.mp4",
                  caption=caption, has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


# --- Document validation ---------------------------------------------------


def test_document_rejects_overlapping_clips():
    with pytest.raises(ValidationError, match="overlap"):
        TimelineDocument(video_tracks=[[_clip(0, 0, 3000), _clip(2000, 0, 2000)]])


def test_document_allows_touching_clips():
    TimelineDocument(video_tracks=[[_clip(0, 0, 2000), _clip(2000, 0, 2000)]])


def test_clip_rejects_inverted_trim():
    with pytest.raises(ValidationError):
        TimelineClip(id="c", asset_id="a", start_ms=0, in_ms=1000, out_ms=500)


def test_text_clip_validation():
    with pytest.raises(ValidationError):
        TextClip(id="t", text="x", start_ms=500, end_ms=500)
    with pytest.raises(ValidationError):
        TextClip(id="t", text="x", start_ms=0, end_ms=100, y_pct=1.4)


# --- Persistence + versioning (the acceptance round-trip) -------------------


def test_save_reload_roundtrip_and_versioning(client, session):
    asset = _seed_asset(session)
    created = client.post("/timelines", json={"title": "Edit me"})
    assert created.status_code == 201, created.text
    timeline = created.json()
    assert timeline["version"] == 1

    doc = {
        "format": "long",
        "transition_ms": 0,
        "video_tracks": [[_clip(0, 250, 1750, asset_id=str(asset.id))]],
        "texts": [{"id": "t1", "text": "Hello", "start_ms": 100, "end_ms": 1200, "y_pct": 0.8}],
    }
    saved = client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2

    reloaded = client.get(f"/timelines/{timeline['id']}").json()
    assert reloaded["doc"] == saved.json()["doc"]
    assert reloaded["doc"]["video_tracks"][0][0]["in_ms"] == 250
    assert reloaded["doc"]["texts"][0]["text"] == "Hello"

    stale = client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})
    assert stale.status_code == 409


def test_save_rejects_invalid_document(client):
    timeline = client.post("/timelines", json={"title": "x y"}).json()
    bad_doc = {"video_tracks": [[_clip(0, 0, 3000), _clip(1000, 0, 2000)]]}
    response = client.put(f"/timelines/{timeline['id']}", json={"doc": bad_doc, "base_version": 1})
    assert response.status_code == 422


# --- Storyboard hand-off ---------------------------------------------------


def _storyboard_with_assets(client, session, count=2) -> str:
    board = client.post("/storyboards", json={"title": "To edit"}).json()
    from schema.models import Shot

    for i in range(count):
        asset = _seed_asset(session, caption=f"shot {i}")
        client.post(
            f"/storyboards/{board['id']}/shots",
            json={"idx": i, "subject": f"s{i}", "preset_ids": [],
                  "asset_id": str(asset.id), "duration_target_ms": 3000},
        )
    return board["id"]


def test_open_storyboard_in_editor(client, session):
    board_id = _storyboard_with_assets(client, session)
    response = client.post(f"/storyboards/{board_id}/edit")
    assert response.status_code == 201, response.text
    doc = response.json()["doc"]
    clips = doc["video_tracks"][0]
    assert [c["start_ms"] for c in clips] == [0, 3000]
    assert all(c["out_ms"] == 3000 and c["in_ms"] == 0 for c in clips)


def test_open_unfinished_storyboard_refused(client):
    board = client.post("/storyboards", json={"title": "Not ready"}).json()
    client.post(
        f"/storyboards/{board['id']}/shots",
        json={"idx": 0, "subject": "pending", "preset_ids": ["zoom_in"]},
    )
    assert client.post(f"/storyboards/{board['id']}/edit").status_code == 409


# --- Media presigning ------------------------------------------------------


def test_media_endpoint_presigns_clip_assets(client, session):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="avatar-pipeline"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store
        asset = _seed_asset(session)
        timeline = client.post("/timelines", json={"title": "x y"}).json()
        doc = {"video_tracks": [[_clip(0, 0, 1000, asset_id=str(asset.id))]]}
        client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})

        media = client.get(f"/timelines/{timeline['id']}/media").json()
        assert str(asset.id) in media
        assert asset.uri.split("/")[-1] in media[str(asset.id)]


# --- Export with trims and text overlays ------------------------------------


def test_export_flattens_trims_and_texts(client, session, dispatcher):
    generated = _seed_asset(session, origin=AssetOrigin.generated)
    own = _seed_asset(session)
    timeline = client.post("/timelines", json={"title": "Trimmed"}).json()
    doc = {
        "video_tracks": [[
            _clip(0, 500, 2000, asset_id=str(generated.id)),
            _clip(1500, 0, 1000, asset_id=str(own.id)),
        ]],
        "texts": [{"id": "t", "text": "Chapter one", "start_ms": 0, "end_ms": 900, "y_pct": 0.75}],
    }
    client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})

    response = client.post(f"/timelines/{timeline['id']}/export")
    assert response.status_code == 202, response.text
    render = response.json()["timeline"]
    assert [s["duration_ms"] for s in render["shots"]] == [1500, 1000]
    assert render["shots"][0]["in_ms"] == 500
    assert render["shots"][0]["origin"] == "generated"
    assert render["texts"][0]["text"] == "Chapter one"
    assert dispatcher.calls[-1][1] == "worker_cpu.stages.export_stage"


def test_compiler_emits_trim_seek_and_text_overlays():
    timeline = {
        "title": "t", "format": "long", "width": 1920, "height": 1080,
        "shots": [
            {"idx": 0, "asset_uri": "s3://b/0.mp4", "origin": "generated",
             "duration_ms": 1500, "in_ms": 500, "subject": "a"},
        ],
        "texts": [{"id": "t", "text": "Chapter one", "start_ms": 200, "end_ms": 900, "y_pct": 0.75}],
    }
    args = build_ffmpeg_args(timeline, ["a.mp4"], "o.mp4", "wm.png", text_pngs=["t0.png"])
    seek_at = args.index("-ss")
    assert args[seek_at + 1] == "0.500"
    graph = args[args.index("-filter_complex") + 1]
    assert "overlay=(W-w)/2:H*0.750-h/2:enable='between(t,0.200,0.900)'" in graph
    # the watermark comes after the text overlays so nothing can cover it
    assert graph.rindex("W-w-24") > graph.index("between")


def test_compiler_requires_png_per_text():
    timeline = {
        "title": "t", "format": "long", "width": 100, "height": 100,
        "shots": [{"idx": 0, "asset_uri": "u", "origin": "own", "duration_ms": 1000, "subject": "a"}],
        "texts": [{"id": "t", "text": "x", "start_ms": 0, "end_ms": 500}],
    }
    with pytest.raises(ValueError, match="png per text"):
        build_ffmpeg_args(timeline, ["a"], "o", None)
