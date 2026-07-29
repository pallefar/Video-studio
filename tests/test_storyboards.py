"""Storyboards, style templates, formats, and export compile (M19)."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from api.routes.generations import get_registry
from pipeline_core.providers import ProviderRegistry
from pipeline_core.styles import STYLE_TEMPLATES, format_spec, get_style, StyleError
from schema.models import Asset, AssetOrigin, VideoFormat
from tests.test_providers import FakeApiProvider


# --- Style registry --------------------------------------------------------


def test_style_registry_is_sane():
    ids = [style.id for style in STYLE_TEMPLATES]
    assert len(set(ids)) == len(ids)
    assert all(style.prompt_suffix for style in STYLE_TEMPLATES)
    with pytest.raises(StyleError):
        get_style("vaporwave_madness")


def test_format_specs():
    long = format_spec(VideoFormat.long)
    short = format_spec(VideoFormat.short)
    assert (long["width"], long["height"]) == (1920, 1080)
    assert long["max_duration_s"] is None
    assert (short["width"], short["height"]) == (1080, 1920)
    assert short["max_duration_s"] == 60


# --- Board + shot CRUD -----------------------------------------------------


def _board(client, **overrides) -> dict:
    payload = {"title": "Why your backlog lies", "format": "long", "style_id": "cinematic_noir"}
    payload.update(overrides)
    response = client.post("/storyboards", json=payload)
    assert response.status_code == 201, response.text
    return response.json()

def _add_shot(client, board_id, idx, subject="hands typing on a keyboard", presets=None, duration_ms=5000):
    return client.post(
        f"/storyboards/{board_id}/shots",
        json={
            "idx": idx,
            "subject": subject,
            "preset_ids": presets or ["zoom_in"],
            "duration_target_ms": duration_ms,
        },
    )


def test_storyboard_lifecycle(client):
    board = _board(client)
    assert board["format"] == "long"
    assert board["shots"] == []

    assert _add_shot(client, board["id"], 0).status_code == 201
    assert _add_shot(client, board["id"], 1, subject="city skyline").status_code == 201
    detail = client.get(f"/storyboards/{board['id']}").json()
    assert [shot["idx"] for shot in detail["shots"]] == [0, 1]

    shot_id = detail["shots"][1]["id"]
    after_delete = client.request("DELETE", f"/storyboards/{board['id']}/shots/{shot_id}").json()
    assert len(after_delete["shots"]) == 1


def test_storyboard_rejects_unknown_style(client):
    response = client.post("/storyboards", json={"title": "x y", "style_id": "nope"})
    assert response.status_code == 422


def test_shot_rejects_duplicate_idx_and_bad_stack(client):
    board = _board(client)
    assert _add_shot(client, board["id"], 0).status_code == 201
    assert _add_shot(client, board["id"], 0).status_code == 409
    bad = _add_shot(client, board["id"], 1, presets=["bullet_time", "zoom_in"])
    assert bad.status_code == 422


# --- Shot generation: style + format flow into the generation --------------


def _fake_registry(client) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    client.app.dependency_overrides[get_registry] = lambda: registry
    return registry


def test_generate_shot_applies_style_and_format(client, dispatcher):
    _fake_registry(client)
    board = _board(client, format="short", style_id="neon_night")
    _add_shot(client, board["id"], 0, subject="a neon alley", duration_ms=90_000)
    shot_id = client.get(f"/storyboards/{board['id']}").json()["shots"][0]["id"]

    response = client.post(
        f"/storyboards/{board['id']}/shots/{shot_id}/generate",
        json={"provider": "fake", "model": "fake-t2v"},
    )
    assert response.status_code == 201, response.text
    shot = response.json()["shots"][0]
    assert shot["generation_status"] == "queued"

    generation = client.get("/generations").json()[-1]
    assert "neon-lit night scene" in generation["prompt"]  # style suffix applied
    params = generation["params"]
    assert (params["width"], params["height"]) == (1080, 1920)  # shorts are 9:16
    assert params["aspect"] == "9:16"
    assert params["duration_s"] == 60  # capped at the shorts limit
    assert params["style"] == "neon_night"
    assert dispatcher.calls[-1][0] == "cpu"


def test_generate_shot_long_format_uncapped(client, dispatcher):
    _fake_registry(client)
    board = _board(client, format="long", style_id=None)
    _add_shot(client, board["id"], 0, duration_ms=12_000)
    shot_id = client.get(f"/storyboards/{board['id']}").json()["shots"][0]["id"]
    client.post(f"/storyboards/{board['id']}/shots/{shot_id}/generate",
                json={"provider": "fake", "model": "fake-t2v"})
    params = client.get("/generations").json()[-1]["params"]
    assert (params["width"], params["height"]) == (1920, 1080)
    assert params["duration_s"] == 12
    assert "style" not in params


# --- Export ---------------------------------------------------------------


def _finish_shot(session: Session, client, board_id: str, shot_idx: int):
    """Simulate a finished take: attach an asset directly to the shot."""
    import uuid as uuid_module

    from schema.models import Shot

    asset = Asset(origin=AssetOrigin.generated, uri=f"s3://t/out{shot_idx}.mp4",
                  caption=f"shot {shot_idx}", has_identifiable_people=False, approved=False)
    session.add(asset)
    session.commit()
    board_uuid = uuid_module.UUID(board_id)
    shot = [s for s in session.exec(
        __import__("sqlmodel").select(Shot).where(Shot.storyboard_id == board_uuid)
    ).all() if s.idx == shot_idx][0]
    shot.asset_id = asset.id
    session.add(shot)
    session.commit()


def test_export_refuses_incomplete_storyboard(client):
    board = _board(client)
    assert client.post(f"/storyboards/{board['id']}/export").status_code == 409  # no shots
    _add_shot(client, board["id"], 0)
    response = client.post(f"/storyboards/{board['id']}/export")
    assert response.status_code == 409
    assert "without a finished asset" in response.json()["detail"]


def test_export_compiles_ordered_timeline(client, session, dispatcher):
    board = _board(client, title="Launch video")
    _add_shot(client, board["id"], 0, subject="opening wide shot", duration_ms=4000)
    _add_shot(client, board["id"], 1, subject="detail close-up", duration_ms=6000)
    _finish_shot(session, client, board["id"], 0)
    _finish_shot(session, client, board["id"], 1)

    response = client.post(f"/storyboards/{board['id']}/export")
    assert response.status_code == 202, response.text
    timeline = response.json()["timeline"]
    assert timeline["format"] == "long"
    assert (timeline["width"], timeline["height"]) == (1920, 1080)
    assert timeline["style"] == "cinematic_noir"
    assert [shot["asset_uri"] for shot in timeline["shots"]] == [
        "s3://t/out0.mp4", "s3://t/out1.mp4",
    ]

    queue_name, func_path, args, job_key = dispatcher.calls[-1]
    assert queue_name == "cpu"
    assert func_path == "worker_cpu.stages.export_stage"
    assert args[1]["shots"][0]["duration_ms"] == 4000
    assert job_key == f"export-{board['id']}"


def test_short_export_enforces_duration_cap(client, session):
    board = _board(client, format="short", style_id=None)
    _add_shot(client, board["id"], 0, duration_ms=40_000)
    _add_shot(client, board["id"], 1, duration_ms=30_000)
    _finish_shot(session, client, board["id"], 0)
    _finish_shot(session, client, board["id"], 1)
    response = client.post(f"/storyboards/{board['id']}/export")
    assert response.status_code == 409
    assert "capped at 60s" in response.json()["detail"]
