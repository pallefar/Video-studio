"""M2 (CPU half) acceptance: VFR sources are rejected at ingest; a seam pop
at the loop boundary is detected by perceptual hash and falls back to
ping-pong playback; a clean CFR loop passes through untouched."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.queues import QUEUE_CPU
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import BaseLoop
from pipeline_core.seam import dhash, hamming_distance
from worker_cpu.ffmpeg.loops import (
    SEAM_MAX_SCORE,
    make_ping_pong,
    seam_score,
    vfr_ratio,
)

SIZE = "192x108"


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def clips(ffmpeg_bin, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("loop-clips")

    clean = tmp / "clean.mp4"  # solid colour: first frame == last frame
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", f"color=c=red:s={SIZE}:d=1:r=25", "-pix_fmt", "yuv420p", str(clean)],
        check=True, capture_output=True,
    )

    seam = tmp / "seam.mp4"  # red half then blue half: boundary pops
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner",
         "-f", "lavfi", "-i", f"color=c=red:s={SIZE}:d=0.5:r=25",
         "-f", "lavfi", "-i", f"color=c=blue:s={SIZE}:d=0.5:r=25",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", "-pix_fmt", "yuv420p", str(seam)],
        check=True, capture_output=True,
    )

    # union of two frame gratings -> genuinely irregular timestamps
    vfr = tmp / "vfr.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", f"testsrc=size={SIZE}:rate=25:duration=1",
         "-vf", "select='not(mod(n,5))+not(mod(n,7))'", "-vsync", "vfr",
         "-pix_fmt", "yuv420p", str(vfr)],
        check=True, capture_output=True,
    )
    return {"clean": clean, "seam": seam, "vfr": vfr}


# --- pure primitives ---------------------------------------------------------


def test_dhash_and_hamming():
    from PIL import Image

    solid = Image.new("RGB", (64, 64), (255, 0, 0))
    also_solid = Image.new("RGB", (64, 64), (250, 5, 5))
    checker = Image.new("RGB", (64, 64))
    checker.putdata(
        [(255 if (x // 8 + y // 8) % 2 else 0,) * 3 for y in range(64) for x in range(64)]
    )

    assert hamming_distance(dhash(solid), dhash(also_solid)) < 0.1
    assert hamming_distance(dhash(solid), dhash(checker)) > 0.2
    assert hamming_distance(dhash(solid), dhash(solid)) == 0.0


def test_color_distance_catches_flat_pops():
    from PIL import Image

    from pipeline_core.seam import color_distance

    red = Image.new("RGB", (64, 64), (255, 0, 0))
    blue = Image.new("RGB", (64, 64), (0, 0, 255))
    assert color_distance(red, blue) > 0.5  # dHash alone scores this 0
    assert color_distance(red, red) == 0.0


def test_vfr_detection(ffmpeg_bin, clips):
    assert vfr_ratio(ffmpeg_bin, clips["clean"]) <= 0.01
    assert vfr_ratio(ffmpeg_bin, clips["vfr"]) > 0.05


def test_seam_scores(ffmpeg_bin, clips, tmp_path):
    assert seam_score(ffmpeg_bin, clips["clean"], tmp_path) <= SEAM_MAX_SCORE
    assert seam_score(ffmpeg_bin, clips["seam"], tmp_path) > SEAM_MAX_SCORE


def test_ping_pong_doubles_duration(ffmpeg_bin, clips, tmp_path):
    out = make_ping_pong(ffmpeg_bin, clips["seam"], tmp_path / "pp.mp4")
    # the mirrored clip starts and ends on the same frame — seamless loop
    assert seam_score(ffmpeg_bin, out, tmp_path) <= SEAM_MAX_SCORE
    probe = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-i", str(out)], capture_output=True, text=True
    )
    assert "00:00:02" in probe.stderr  # 1 s source -> 2 s ping-pong


# --- the stage ---------------------------------------------------------------


def _loop_row(session: Session, store: ObjectStore, clip: Path, name: str) -> str:
    key = f"loops/src/{name}.mp4"
    store.put_file(key, clip)
    loop = BaseLoop(name=name, source_uri=store.uri_for(key), fps=25.0, frame_count=25)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    return str(loop.id)


@pytest.fixture()
def store_env(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="loop-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        yield store


def test_clean_loop_passes(store_env, engine, session, clips):
    loop_id = _loop_row(session, store_env, clips["clean"], "clean")
    cpu_stages.loop_preprocess_stage(loop_id)
    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.error is None
        assert loop.vfr_ratio <= 0.01
        assert loop.seam_score <= SEAM_MAX_SCORE
        assert loop.ping_pong is False
        assert loop.source_uri.endswith("loops/src/clean.mp4")  # untouched


def test_vfr_loop_rejected_at_ingest(store_env, engine, session, clips):
    loop_id = _loop_row(session, store_env, clips["vfr"], "vfr")
    cpu_stages.loop_preprocess_stage(loop_id)
    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.error is not None and "VFR" in loop.error
        assert loop.ping_pong is False


def test_seam_pop_falls_back_to_ping_pong(store_env, engine, session, clips):
    loop_id = _loop_row(session, store_env, clips["seam"], "seam")
    cpu_stages.loop_preprocess_stage(loop_id)
    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.seam_score > SEAM_MAX_SCORE
        assert loop.ping_pong is True
        assert loop.source_uri.endswith(f"loops/{loop_id}/pingpong.mp4")
        assert loop.frame_count == 50  # doubled
        assert store_env.exists(f"loops/{loop_id}/pingpong.mp4")

    # idempotent: a replayed job must not ping-pong the ping-pong
    cpu_stages.loop_preprocess_stage(loop_id)
    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.frame_count == 50


# --- ingest wiring -----------------------------------------------------------


def test_loop_create_enqueues_preprocess(client, dispatcher):
    response = client.post(
        "/loops",
        json={"name": "desk", "source_uri": "s3://b/l.mp4", "fps": 25.0, "frame_count": 750},
    )
    assert response.status_code == 201, response.text
    loop_id = response.json()["id"]
    queue, func_path, args, job_key = dispatcher.calls[-1]
    assert queue == QUEUE_CPU
    assert func_path == "worker_cpu.stages.loop_preprocess_stage"
    assert args == (loop_id,)
    assert job_key == f"{loop_id}-loop_preprocess"

    # manual re-run endpoint
    rerun = client.post(f"/loops/{loop_id}/preprocess")
    assert rerun.status_code == 202
