"""M24 library intelligence: Florence-2 auto-captioning wiring — placeholder
heuristic, caption_stage idempotency and re-embedding, ingest-tail enqueue,
API route, and the backfill script. The real model is a workstation install
([caption] extra); tests inject a fake captioner."""

from __future__ import annotations

import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.captioner import NoopCaptioner, get_captioner, is_placeholder_caption
from pipeline_core.embeddings import cosine, get_embedder
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin


class FakeCaptioner:
    available = True

    def __init__(self, text="a red vintage car parked on a rainy neon street"):
        self.text = text
        self.calls = 0

    def caption(self, image_bytes: bytes) -> str:
        assert image_bytes  # the stage must hand over real frame bytes
        self.calls += 1
        return self.text


# --- Placeholder heuristic ---------------------------------------------------


@pytest.mark.parametrize("caption", [
    None,
    "",
    "   ",
    "IMG_2041.mp4",
    "clip.png",
    "upload_3",
    "untitled",
    "asset 12",
    "8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77.mp4",
])
def test_placeholder_captions_detected(caption):
    assert is_placeholder_caption(caption)


@pytest.mark.parametrize("caption", [
    "a red vintage car parked on a rainy neon street",
    "city drive establishing shot",
    "signal bars interstitial",
])
def test_real_captions_kept(caption):
    assert not is_placeholder_caption(caption)


def test_captioner_defaults_to_noop_without_extra():
    # transformers isn't installed in CI — the factory must degrade, not raise
    captioner = get_captioner()
    assert isinstance(captioner, NoopCaptioner)
    assert captioner.caption(b"bytes") is None


# --- caption_stage -----------------------------------------------------------


@pytest.fixture()
def caption_env(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    fake = FakeCaptioner()
    monkeypatch.setattr(cpu_stages, "_captioner", fake)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="cap-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda *a, **k: store)
        yield {"engine": engine, "store": store, "fake": fake}


def _seed_asset(engine, caption, uri="s3://cap-test/clip.mp4") -> str:
    with Session(engine) as session:
        asset = Asset(origin=AssetOrigin.own, uri=uri, caption=caption,
                      has_identifiable_people=False, approved=True)
        session.add(asset)
        session.commit()
        return str(asset.id)


def test_caption_stage_writes_caption_and_embedding(caption_env):
    asset_id = _seed_asset(caption_env["engine"], caption="IMG_2041.mp4")
    caption_env["store"].put_bytes(
        f"assets/derived/{asset_id}/poster.jpg", b"jpeg-bytes"
    )

    result = cpu_stages.caption_stage(asset_id)

    assert result == caption_env["fake"].text
    with Session(caption_env["engine"]) as session:
        asset = session.get(Asset, uuid.UUID(asset_id))
        assert asset.caption == caption_env["fake"].text
        # re-embedded: the resolver can now find it by content
        query = get_embedder().embed("vintage car in neon rain")
        assert cosine(query, asset.embedding) > 0.1


def test_caption_stage_respects_real_captions(caption_env):
    asset_id = _seed_asset(caption_env["engine"], caption="city drive establishing shot")
    caption_env["store"].put_bytes(f"assets/derived/{asset_id}/poster.jpg", b"jpeg")

    assert cpu_stages.caption_stage(asset_id) is None
    assert caption_env["fake"].calls == 0

    # force=True is the --recaption path: overwrite is explicit, never implicit
    assert cpu_stages.caption_stage(asset_id, True) == caption_env["fake"].text


def test_caption_stage_uses_image_asset_directly(caption_env):
    asset_id = _seed_asset(
        caption_env["engine"], caption=None, uri="s3://cap-test/still.png"
    )
    caption_env["store"].put_bytes("still.png", b"png-bytes")

    assert cpu_stages.caption_stage(asset_id) == caption_env["fake"].text


def test_caption_stage_skips_without_frame_source(caption_env):
    # a video with no poster derivative yet: skip gracefully, don't crash
    asset_id = _seed_asset(caption_env["engine"], caption=None)
    assert cpu_stages.caption_stage(asset_id) is None
    assert caption_env["fake"].calls == 0


def test_caption_stage_noop_leaves_caption_unchanged(caption_env, monkeypatch):
    monkeypatch.setattr(cpu_stages, "_captioner", NoopCaptioner())
    asset_id = _seed_asset(caption_env["engine"], caption="IMG_1.mp4")
    caption_env["store"].put_bytes(f"assets/derived/{asset_id}/poster.jpg", b"jpeg")

    assert cpu_stages.caption_stage(asset_id) is None
    with Session(caption_env["engine"]) as session:
        assert session.get(Asset, uuid.UUID(asset_id)).caption == "IMG_1.mp4"


# --- API route ---------------------------------------------------------------


def test_caption_route_enqueues_cpu_job(client, session, dispatcher):
    asset = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/a.mp4",
                  caption=None, has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)

    response = client.post(f"/assets/{asset.id}/caption?force=true")
    assert response.status_code == 202
    queue, func, args, job_key = dispatcher.calls[-1]
    assert queue == "cpu"
    assert func == "worker_cpu.stages.caption_stage"
    assert args == (str(asset.id), True)
    assert job_key == f"caption-{asset.id}"


def test_caption_route_404_on_unknown_asset(client):
    assert client.post(f"/assets/{uuid.uuid4()}/caption").status_code == 404


# --- Backfill script ---------------------------------------------------------


def test_backfill_embeds_and_queues_recaption(engine, monkeypatch, capsys):
    import scripts.backfill_embeddings as backfill

    with Session(engine) as session:
        # embedded caption missing its vector (pre-fix row)
        stale = Asset(origin=AssetOrigin.own, uri="s3://b/one.mp4",
                      caption="drone shot over a mountain lake",
                      has_identifiable_people=False, approved=True)
        # placeholder caption -> recaption candidate
        placeholder = Asset(origin=AssetOrigin.own, uri="s3://b/two.mp4",
                            caption="IMG_2041.mp4",
                            has_identifiable_people=False, approved=True)
        session.add(stale)
        session.add(placeholder)
        session.commit()
        stale_id, placeholder_id = str(stale.id), str(placeholder.id)

    calls = []

    class RecordingDispatcher:
        def enqueue(self, queue, func, *args, job_key=None):
            calls.append((queue, func, args))

    monkeypatch.setattr(backfill, "get_engine", lambda: engine)
    monkeypatch.setattr(backfill, "Dispatcher", RecordingDispatcher)
    monkeypatch.setattr("sys.argv", ["backfill_embeddings.py", "--recaption"])

    assert backfill.main() == 0

    with Session(engine) as session:
        assert session.get(Asset, uuid.UUID(stale_id)).embedding  # vector filled
    assert calls == [("cpu", "worker_cpu.stages.caption_stage", (placeholder_id, True))]
