"""M14: ingest derivatives — probe, proxy, sprites + VTT, waveform peaks —
against real ffmpeg, plus the derived-media API and proxy preference."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin
from worker_cpu.ffmpeg import ingest as ing


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def av_clip(ffmpeg_bin, tmp_path_factory) -> Path:
    """3 s 1920x1080 clip WITH an audio track (sine tone)."""
    path = tmp_path_factory.mktemp("ingest") / "av.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner",
         "-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=3:r=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True, capture_output=True,
    )
    return path


def test_probe_parses_stream_info(ffmpeg_bin, av_clip):
    info = ing.probe(ffmpeg_bin, av_clip)
    assert 2800 <= info["duration_ms"] <= 3300
    assert (info["width"], info["height"]) == (1920, 1080)
    assert info["fps"] == 25.0
    assert info["has_audio"] is True


def test_probe_non_video_returns_no_duration(ffmpeg_bin, tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not a video at all")
    info = ing.probe(ffmpeg_bin, junk)
    assert info["duration_ms"] is None


def test_proxy_downscales_to_720(ffmpeg_bin, av_clip, tmp_path):
    proxy = ing.make_proxy(ffmpeg_bin, av_clip, tmp_path / "proxy.mp4", has_audio=True)
    info = ing.probe(ffmpeg_bin, proxy)
    assert info["height"] == 720
    assert info["has_audio"] is True
    assert proxy.stat().st_size < av_clip.stat().st_size


def test_sprite_plan_and_vtt_grid():
    plan = ing.sprite_plan(duration_ms=25_000, width=1920, height=1080)
    assert plan["interval_s"] == 1
    assert plan["count"] == 25
    assert plan["thumb_h"] == 90
    vtt = ing.make_vtt(plan, 25_000)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in vtt
    assert "sprite.jpg#xywh=0,0,160,90" in vtt
    # thumb 11 wraps to the second row
    assert "sprite.jpg#xywh=0,90,160,90" in vtt


def test_sprites_render(ffmpeg_bin, av_clip, tmp_path):
    plan = ing.sprite_plan(3000, 1920, 1080)
    sprite = ing.make_sprites(ffmpeg_bin, av_clip, tmp_path / "sprite.jpg", plan)
    from PIL import Image

    image = Image.open(sprite)
    assert image.size[0] == plan["cols"] * plan["thumb_w"]


def test_waveform_peaks_detect_tone_and_silence(ffmpeg_bin, av_clip, clips_dir=None):
    peaks = ing.waveform_peaks(ffmpeg_bin, av_clip, buckets=100)
    assert len(peaks) >= 50
    assert max(peaks) > 0.05  # the sine tone registers clearly above silence
    assert all(0 <= p <= 1 for p in peaks)


def test_waveform_empty_without_audio(ffmpeg_bin, tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", "color=c=red:s=192x108:d=1:r=25", "-pix_fmt", "yuv420p", str(silent)],
        check=True, capture_output=True,
    )
    assert ing.waveform_peaks(ffmpeg_bin, silent) == []


def test_ingest_stage_end_to_end(ffmpeg_bin, av_clip, engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="ingest-e2e"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        store.put_file("assets/src.mp4", av_clip)

        with Session(engine) as session:
            asset = Asset(origin=AssetOrigin.own, uri="s3://ingest-e2e/assets/src.mp4",
                          caption="ingest me", has_identifiable_people=False, approved=True)
            session.add(asset)
            session.commit()
            asset_id = str(asset.id)

        info = cpu_stages.ingest_stage(asset_id)
        assert info["has_audio"] is True

        prefix = f"assets/derived/{asset_id}"
        for name in ["proxy.mp4", "sprite.jpg", "sprite.vtt", "peaks.json"]:
            assert store.exists(f"{prefix}/{name}"), f"missing {name}"
        peaks = json.loads(store.get_bytes(f"{prefix}/peaks.json"))
        assert peaks and max(peaks) > 0.05

        with Session(engine) as session:
            assert session.get(Asset, uuid.UUID(asset_id)).duration_ms is not None

        # idempotent second run
        assert cpu_stages.ingest_stage(asset_id) is None


def test_ingest_endpoint_and_derived_media(client, session, dispatcher):
    asset = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/a.mp4",
                  caption="x", has_identifiable_people=False, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)

    queued = client.post(f"/assets/{asset.id}/ingest")
    assert queued.status_code == 202
    assert dispatcher.calls[-1][1] == "worker_cpu.stages.ingest_stage"

    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="avatar-pipeline"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store
        # only proxy + peaks exist
        store.put_bytes(f"assets/derived/{asset.id}/proxy.mp4", b"v")
        store.put_bytes(f"assets/derived/{asset.id}/peaks.json", b"[]")
        derived = client.get(f"/assets/{asset.id}/derived").json()
        assert set(derived) == {"proxy", "peaks"}


def test_timeline_media_prefers_proxy(client, session):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="avatar-pipeline"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store

        asset = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/orig.mp4",
                      caption="x", has_identifiable_people=False, approved=True)
        session.add(asset)
        session.commit()
        session.refresh(asset)
        store.put_bytes("orig.mp4", b"o")
        store.put_bytes(f"assets/derived/{asset.id}/proxy.mp4", b"p")

        timeline = client.post("/timelines", json={"title": "x y"}).json()
        doc = {"video_tracks": [[{"id": "c", "asset_id": str(asset.id), "start_ms": 0, "out_ms": 1000}]]}
        client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})

        media = client.get(f"/timelines/{timeline['id']}/media").json()
        assert "derived" in media[str(asset.id)]  # proxy preferred over original
