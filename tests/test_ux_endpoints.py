"""UX-loop endpoints: batch thumbnails and export ready/download status."""

from __future__ import annotations

from moto import mock_aws

from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore


def _store(client):
    store = ObjectStore(Settings(s3_endpoint="", s3_bucket="avatar-pipeline"))
    store.ensure_bucket()
    client.app.dependency_overrides[get_object_store] = lambda: store
    return store


def test_thumbs_batch_endpoint(client, session):
    """One call, every thumbnail — anchored on real Asset rows (the M17+
    implementation): ingested assets use their derived sprite, image assets
    fall back to the image itself, un-ingested video gets nothing."""
    from schema.models import Asset, AssetOrigin

    with mock_aws():
        store = _store(client)
        ingested = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/clips/a.mp4",
                         caption="a", has_identifiable_people=False)
        image = Asset(origin=AssetOrigin.generated, uri="s3://avatar-pipeline/stills/b.png",
                      caption="b", has_identifiable_people=False)
        raw = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/clips/c.mp4",
                    caption="c", has_identifiable_people=False)
        session.add_all([ingested, image, raw])
        session.commit()
        store.put_bytes(f"assets/derived/{ingested.id}/sprite.jpg", b"jpg")
        store.put_bytes("stills/b.png", b"png")

        thumbs = client.get("/assets/thumbs").json()
        assert set(thumbs) == {str(ingested.id), str(image.id)}  # raw video: none yet
        assert "sprite.jpg" in thumbs[str(ingested.id)]


def test_storyboard_export_status_closes_the_loop(client):
    with mock_aws():
        store = _store(client)
        board = client.post("/storyboards", json={"title": "Loop"}).json()

        before = client.get(f"/storyboards/{board['id']}/export/status").json()
        assert before == {"ready": False, "url": None}

        store.put_bytes(f"renders/{board['id']}/final.mp4", b"video")
        after = client.get(f"/storyboards/{board['id']}/export/status").json()
        assert after["ready"] is True
        assert f"renders/{board['id']}/final.mp4" in after["url"]


def test_timeline_export_status(client):
    with mock_aws():
        store = _store(client)
        timeline = client.post("/timelines", json={"title": "x y"}).json()

        assert client.get(f"/timelines/{timeline['id']}/export/status").json()["ready"] is False
        store.put_bytes(f"renders/{timeline['id']}/final.mp4", b"video")
        status = client.get(f"/timelines/{timeline['id']}/export/status").json()
        assert status["ready"] is True
