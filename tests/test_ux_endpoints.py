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


def test_thumbs_batch_endpoint(client):
    with mock_aws():
        store = _store(client)
        store.put_bytes("assets/derived/aaa/sprite.jpg", b"jpg")
        store.put_bytes("assets/derived/bbb/sprite.jpg", b"jpg")
        store.put_bytes("assets/derived/ccc/proxy.mp4", b"mp4")  # no sprite yet

        thumbs = client.get("/assets/thumbs").json()
        assert set(thumbs) == {"aaa", "bbb"}
        assert "sprite.jpg" in thumbs["aaa"]


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
