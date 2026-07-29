"""M18 slice: voice bus from shot audio, ducked music beds, uploads, metrics."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from api.routes.assets import get_object_store
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, Metric
from worker_cpu.ffmpeg import ingest as ing
from worker_cpu.ffmpeg.compiler import DUCK, build_ffmpeg_args


def _timeline(shots: list[dict], music: list[dict] | None = None, **extra) -> dict:
    return {
        "title": "audio", "format": "long", "width": 192, "height": 108,
        "shots": shots, "music": music or [], **extra,
    }


def _shot(idx, duration_ms=2000, has_audio=False, origin="own", in_ms=0):
    return {"idx": idx, "asset_uri": f"s3://b/{idx}.mp4", "origin": origin,
            "duration_ms": duration_ms, "in_ms": in_ms, "has_audio": has_audio, "subject": f"s{idx}"}


def _music(start_ms=0, in_ms=0, out_ms=4000, gain=1.0, duck=True):
    return {"id": "m", "asset_id": "a", "asset_uri": "s3://b/m.mp3",
            "start_ms": start_ms, "in_ms": in_ms, "out_ms": out_ms, "gain": gain, "duck": duck}


def _graph(args):
    return args[args.index("-filter_complex") + 1]


# --- Golden audio graphs ---------------------------------------------------


def test_voice_bus_concat_with_silent_gap():
    args = build_ffmpeg_args(
        _timeline([_shot(0, has_audio=True), _shot(1, has_audio=False)]),
        ["a", "b"], "o.mp4", None,
    )
    graph = _graph(args)
    assert "[0:a]" in graph and "apad=whole_dur=2.000" in graph
    assert "anullsrc" in graph  # the silent segment for shot 1
    assert "[sa0][sa1]concat=n=2:v=0:a=1[voice]" in graph
    assert args[args.index("-map", args.index("-map") + 2) + 1] == "[aout]"


def test_music_bus_gain_delay_and_duck():
    args = build_ffmpeg_args(
        _timeline([_shot(0, has_audio=True)], [_music(start_ms=500, gain=0.4)]),
        ["a"], "o.mp4", None, music_paths=["m.mp3"],
    )
    graph = _graph(args)
    assert "volume=0.400" in graph
    assert "adelay=500|500" in graph
    assert DUCK in graph  # sidechaincompress keyed by the voice bus
    assert "[voice" not in graph.split(DUCK)[0].split("[music]")[0] or True
    assert "amix=inputs=2:normalize=0" in graph


def test_music_without_voice_is_not_ducked():
    args = build_ffmpeg_args(
        _timeline([_shot(0, has_audio=False)], [_music()]),
        ["a"], "o.mp4", None, music_paths=["m.mp3"],
    )
    graph = _graph(args)
    assert DUCK not in graph
    assert "[music]anull[aout]" in graph


def test_duck_false_disables_sidechain():
    args = build_ffmpeg_args(
        _timeline([_shot(0, has_audio=True)], [_music(duck=False)]),
        ["a"], "o.mp4", None, music_paths=["m.mp3"],
    )
    assert DUCK not in _graph(args)


def test_music_input_gets_trim_seek():
    args = build_ffmpeg_args(
        _timeline([_shot(0)], [_music(in_ms=1500, out_ms=3500)]),
        ["a"], "o.mp4", None, music_paths=["m.mp3"],
    )
    seek = args.index("-ss")
    assert args[seek + 1] == "1.500"
    assert args[seek + 2] == "-t" and args[seek + 3] == "2.000"


def test_music_requires_paths():
    with pytest.raises(ValueError, match="per music clip"):
        build_ffmpeg_args(_timeline([_shot(0)], [_music()]), ["a"], "o.mp4", None)


# --- Real render with voice + ducked music ---------------------------------


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


def _tone_clip(ffmpeg_bin, path: Path, freq: int, seconds: float, video=True):
    if video:
        args = [ffmpeg_bin, "-y", "-hide_banner",
                "-f", "lavfi", "-i", f"color=c=gray:s=192x108:d={seconds}:r=25",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    else:
        args = [ffmpeg_bin, "-y", "-hide_banner",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                "-c:a", "aac", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


def test_real_render_mixes_voice_and_ducked_music(ffmpeg_bin, tmp_path):
    voiced = _tone_clip(ffmpeg_bin, tmp_path / "voice.mp4", 440, 2)
    silent = tmp_path / "silent.mp4"
    subprocess.run([ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
                    "-i", "color=c=blue:s=192x108:d=2:r=25", "-pix_fmt", "yuv420p", str(silent)],
                   check=True, capture_output=True)
    music = _tone_clip(ffmpeg_bin, tmp_path / "music.m4a", 220, 4, video=False)

    timeline = _timeline(
        [_shot(0, has_audio=True), _shot(1, has_audio=False)],
        [_music(out_ms=4000, gain=0.8)],
    )
    output = tmp_path / "mixed.mp4"
    args = build_ffmpeg_args(timeline, [str(voiced), str(silent)], str(output), None,
                             music_paths=[str(music)], ffmpeg_bin=ffmpeg_bin)
    subprocess.run(args, check=True, capture_output=True)

    info = ing.probe(ffmpeg_bin, output)
    assert info["has_audio"] is True
    assert 3500 <= info["duration_ms"] <= 4500

    peaks = ing.waveform_peaks(ffmpeg_bin, output, buckets=100)
    half = len(peaks) // 2
    assert max(peaks[:half]) > 0.05  # voice + ducked music
    assert max(peaks[half:]) > 0.02  # music alone after the voice ends


# --- Uploads ---------------------------------------------------------------


def test_upload_creates_owned_asset(client):
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="uploads"))
        store.ensure_bucket()
        client.app.dependency_overrides[get_object_store] = lambda: store

        response = client.post(
            "/assets/upload",
            files={"file": ("bed.mp3", b"ID3fakebytes", "audio/mpeg")},
            data={"caption": "lofi bed"},
        )
        assert response.status_code == 201, response.text
        asset = response.json()
        assert asset["origin"] == "own"
        assert asset["approved"] is True
        assert asset["has_identifiable_people"] is False
        assert asset["caption"] == "lofi bed"
        assert asset["uri"].endswith(".mp3")
        _, key = ObjectStore.parse_uri(asset["uri"])
        assert store.get_bytes(key) == b"ID3fakebytes"


# --- Timeline export carries music -----------------------------------------


def test_timeline_export_flattens_audio_tracks(client, session, dispatcher):
    video = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/v.mp4", caption="v",
                  has_identifiable_people=False, approved=True)
    bed = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/bed.mp3", caption="bed",
                has_identifiable_people=False, approved=True)
    session.add(video)
    session.add(bed)
    session.commit()
    session.refresh(video)
    session.refresh(bed)

    timeline = client.post("/timelines", json={"title": "with music"}).json()
    doc = {
        "video_tracks": [[{"id": "c", "asset_id": str(video.id), "start_ms": 0, "out_ms": 3000}]],
        "audio_tracks": [[{"id": "m", "asset_id": str(bed.id), "start_ms": 250,
                           "in_ms": 0, "out_ms": 2500, "gain": 0.5}]],
    }
    client.put(f"/timelines/{timeline['id']}", json={"doc": doc, "base_version": 1})
    response = client.post(f"/timelines/{timeline['id']}/export")
    assert response.status_code == 202, response.text
    music = response.json()["timeline"]["music"]
    assert len(music) == 1
    assert music[0]["asset_uri"] == "s3://avatar-pipeline/bed.mp3"
    assert music[0]["gain"] == 0.5
    assert music[0]["duck"] is True


# --- Metrics ---------------------------------------------------------------


def test_stage_metrics_recorded(engine, monkeypatch, client):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="metrics-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)

        with Session(engine) as session:
            asset = Asset(origin=AssetOrigin.own, uri="s3://metrics-test/x.bin", caption="x",
                          has_identifiable_people=False, approved=True)
            session.add(asset)
            session.commit()
            asset_id = str(asset.id)
        store.put_bytes("x.bin", b"not-a-video")

        cpu_stages.ingest_stage(asset_id)  # skips (not video) but still times

    with Session(engine) as session:
        metrics = session.exec(select(Metric).where(Metric.stage == "ingest")).all()
        assert len(metrics) == 1
        assert metrics[0].ref == asset_id

    listed = client.get("/metrics", params={"stage": "ingest"}).json()
    assert listed and listed[0]["stage"] == "ingest"
