"""Dashboard endpoints (panel home tab), library thumbnails, and shot
drag-reorder: /stats, /assets/thumbs, /storyboards/{id}/shots/reorder."""

from __future__ import annotations

import uuid

from moto import mock_aws
from sqlmodel import Session

from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, Identity, Metric, utcnow


def _asset(session: Session, uri: str, caption="clip", approved=True) -> Asset:
    asset = Asset(origin=AssetOrigin.own, uri=uri, caption=caption,
                  has_identifiable_people=False, approved=approved, duration_ms=1000)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


# --- /stats -----------------------------------------------------------------


def test_stats_shape_and_counts(client, session):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="stats-test"))
        store.ensure_bucket()
        store.put_bytes("a.bin", b"12345")
        store.put_bytes("b.bin", b"1234567890")
        client.app.dependency_overrides[get_object_store] = lambda: store

        _asset(session, "s3://stats-test/one.mp4", caption="one")
        _asset(session, "s3://stats-test/two.mp4", caption="two", approved=False)
        session.add(Identity(name="i1", reference_asset_ids=[],
                             consent_recorded_by="karsten", consent_at=utcnow()))
        session.add(Identity(name="i2", reference_asset_ids=[]))
        session.add(Metric(stage="export", ref="r1", duration_ms=1234))
        session.commit()

        body = client.get("/stats").json()

    assert body["assets"]["total"] == 2
    assert body["assets"]["approved"] == 1
    assert body["assets"]["by_origin"] == {"own": 2}
    assert body["identities"] == {"total": 2, "consented": 1}
    assert body["storage"] == {"objects": 2, "bytes": 15}
    assert [a["caption"] for a in body["recent_assets"][:2]] == ["two", "one"]
    assert body["recent_stages"][0]["stage"] == "export"
    assert body["recent_stages"][0]["duration_ms"] == 1234


def test_stats_survives_store_outage(client, session, monkeypatch):
    import api.routes.stats as stats_route

    monkeypatch.setitem(stats_route._usage_cache, "value", None)  # drop the TTL cache

    class ExplodingStore:
        def usage(self):
            raise RuntimeError("minio down")

    client.app.dependency_overrides[get_object_store] = lambda: ExplodingStore()
    body = client.get("/stats").json()
    assert body["storage"] == {"objects": 0, "bytes": 0}


# --- /assets/thumbs ----------------------------------------------------------


def test_thumbs_prefer_poster_then_sprite_then_image(client, session):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="thumb-test"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store

        video = _asset(session, "s3://thumb-test/video.mp4", caption="ingested video")
        legacy = _asset(session, "s3://thumb-test/old.mp4", caption="sprite-only ingest")
        image = _asset(session, "s3://thumb-test/still.png", caption="an image")
        plain = _asset(session, "s3://thumb-test/raw.mp4", caption="never ingested")
        foreign = _asset(session, "s3://SOME-other-bucket/pic.png", caption="foreign uri")

        store.put_bytes(f"assets/derived/{video.id}/poster.jpg", b"poster")
        store.put_bytes(f"assets/derived/{video.id}/sprite.jpg", b"sprite")
        store.put_bytes(f"assets/derived/{legacy.id}/sprite.jpg", b"sprite")
        store.put_bytes("still.png", b"png")

        thumbs = client.get("/assets/thumbs").json()

    assert f"assets/derived/{video.id}/poster.jpg" in thumbs[str(video.id)]  # poster wins
    assert f"assets/derived/{legacy.id}/sprite.jpg" in thumbs[str(legacy.id)]
    assert "still.png" in thumbs[str(image.id)]
    assert str(plain.id) not in thumbs  # no derivative, not an image -> placeholder
    # never sign for a key the uri doesn't point at (download_asset's guard)
    assert str(foreign.id) not in thumbs


# --- shot reorder ------------------------------------------------------------


def _board_with_shots(client, session, count=3):
    board = client.post("/storyboards", json={"title": "Reorder me"}).json()
    shot_ids = []
    for index in range(count):
        asset = _asset(session, f"s3://b/shot{index}.mp4", caption=f"shot {index}")
        read = client.post(
            f"/storyboards/{board['id']}/shots",
            json={"idx": index, "subject": f"beat {index}", "preset_ids": [],
                  "asset_id": str(asset.id)},
        ).json()
        shot_ids = [s["id"] for s in read["shots"]]
    return board["id"], shot_ids


def test_reorder_renumbers_and_persists(client, session):
    board_id, ids = _board_with_shots(client, session)
    new_order = [ids[2], ids[0], ids[1]]

    response = client.post(
        f"/storyboards/{board_id}/shots/reorder", json={"shot_ids": new_order}
    )
    assert response.status_code == 200, response.text
    shots = response.json()["shots"]
    assert [s["id"] for s in shots] == new_order
    assert [s["idx"] for s in shots] == [0, 1, 2]
    assert [s["subject"] for s in shots] == ["beat 2", "beat 0", "beat 1"]

    # persisted: a fresh read shows the same order
    again = client.get(f"/storyboards/{board_id}").json()
    assert [s["id"] for s in again["shots"]] == new_order


def test_reorder_requires_exact_permutation(client, session):
    board_id, ids = _board_with_shots(client, session)
    missing = client.post(
        f"/storyboards/{board_id}/shots/reorder", json={"shot_ids": ids[:2]}
    )
    assert missing.status_code == 422
    foreign = client.post(
        f"/storyboards/{board_id}/shots/reorder",
        json={"shot_ids": [*ids[:2], str(uuid.uuid4())]},
    )
    assert foreign.status_code == 422
    duplicate = client.post(
        f"/storyboards/{board_id}/shots/reorder",
        json={"shot_ids": [ids[0], ids[0], ids[1]]},
    )
    assert duplicate.status_code == 422
    unknown_board = client.post(
        f"/storyboards/{uuid.uuid4()}/shots/reorder", json={"shot_ids": ids}
    )
    assert unknown_board.status_code == 404


def test_reorder_survives_legacy_negative_idx(client, session):
    """ge=0 guards the API edge now, but pre-existing rows may carry negative
    idx — the disjoint parking scheme must not collide with them."""
    from schema.models import Shot, Storyboard

    board = client.post("/storyboards", json={"title": "Legacy board"}).json()
    asset_a = _asset(session, "s3://b/a.mp4", caption="a")
    asset_b = _asset(session, "s3://b/b.mp4", caption="b")
    board_id = uuid.UUID(board["id"])
    session.add(Shot(storyboard_id=board_id, idx=-1, subject="legacy", preset_ids=[],
                     asset_id=asset_a.id))
    session.add(Shot(storyboard_id=board_id, idx=0, subject="modern", preset_ids=[],
                     asset_id=asset_b.id))
    session.commit()
    ids = [str(s.id) for s in session.exec(
        __import__("sqlmodel").select(Shot).where(Shot.storyboard_id == board_id)
    ).all()]

    response = client.post(f"/storyboards/{board_id}/shots/reorder",
                           json={"shot_ids": list(reversed(ids))})
    assert response.status_code == 200, response.text
    assert [s["idx"] for s in response.json()["shots"]] == [0, 1]


def test_add_shot_rejects_negative_idx(client, session):
    board = client.post("/storyboards", json={"title": "Guard board"}).json()
    asset = _asset(session, "s3://b/g.mp4", caption="g")
    response = client.post(
        f"/storyboards/{board['id']}/shots",
        json={"idx": -1, "subject": "nope", "preset_ids": [], "asset_id": str(asset.id)},
    )
    assert response.status_code == 422


def test_stats_timestamps_are_timezone_explicit(client, session):
    session.add(Metric(stage="export", ref="tz", duration_ms=10))
    session.commit()
    client.app.dependency_overrides[get_object_store] = lambda: type(
        "S", (), {"usage": lambda self: {"objects": 0, "bytes": 0}}
    )()
    row = client.get("/stats").json()["recent_stages"][0]
    assert row["created_at"].endswith("+00:00") or row["created_at"].endswith("Z")


def test_reorder_flows_into_export_order(client, session, dispatcher):
    board_id, ids = _board_with_shots(client, session)
    client.post(f"/storyboards/{board_id}/shots/reorder",
                json={"shot_ids": [ids[1], ids[2], ids[0]]})
    export = client.post(f"/storyboards/{board_id}/export")
    assert export.status_code == 202, export.text
    subjects = [s["subject"] for s in export.json()["timeline"]["shots"]]
    assert subjects == ["beat 1", "beat 2", "beat 0"]
