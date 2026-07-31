"""M16 progress reporting: ffmpeg -progress parsed into the metrics table
while a render runs, and exposed per export ref for the panel to poll."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Metric
from worker_cpu.ffmpeg.compiler import expected_duration_ms
from worker_cpu.ffmpeg.progress import parse_progress_blocks, rendered_ms, run_ffmpeg_with_progress


# --- pure parsing -----------------------------------------------------------


def test_parse_progress_blocks_groups_on_progress_key():
    stream = iter(
        [
            "frame=10\n", "out_time_us=400000\n", "speed=2.1x\n", "progress=continue\n",
            "frame=50\n", "out_time_us=2000000\n", "progress=end\n",
        ]
    )
    blocks = list(parse_progress_blocks(stream))
    assert len(blocks) == 2
    assert blocks[0]["progress"] == "continue"
    assert rendered_ms(blocks[0]) == 400
    assert rendered_ms(blocks[1]) == 2000


def test_rendered_ms_falls_back_to_out_time_ms_as_microseconds():
    # ffmpeg's out_time_ms is a misnomer: it reports microseconds too
    assert rendered_ms({"out_time_ms": "1500000"}) == 1500
    assert rendered_ms({"out_time_us": "N/A"}) is None
    assert rendered_ms({}) is None


def test_expected_duration_subtracts_xfade_overlap():
    shots = [{"duration_ms": 2000}, {"duration_ms": 2000}, {"duration_ms": 2000}]
    assert expected_duration_ms({"shots": shots}) == 6000
    assert expected_duration_ms({"shots": shots, "transition_ms": 500}) == 5000
    assert expected_duration_ms({"shots": shots[:1], "transition_ms": 500}) == 2000


# --- the runner against real ffmpeg -----------------------------------------


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def clip(ffmpeg_bin, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("clips") / "green.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", "color=c=green:s=192x108:d=2:r=25",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


def test_runner_reports_positions_and_output_lands(ffmpeg_bin, clip, tmp_path):
    positions: list[int] = []
    output = tmp_path / "out.mp4"
    run_ffmpeg_with_progress(
        [ffmpeg_bin, "-y", "-hide_banner", "-i", str(clip), "-c:v", "libx264", str(output)],
        on_progress=positions.append,
    )
    assert output.stat().st_size > 1000
    assert positions, "no progress blocks parsed"
    assert positions == sorted(positions)
    assert positions[-1] >= 1900  # reached the end of the 2 s clip


def test_runner_raises_with_stderr_tail_on_failure(ffmpeg_bin, tmp_path):
    with pytest.raises(RuntimeError, match="doomed"):
        run_ffmpeg_with_progress(
            [ffmpeg_bin, "-y", "-i", str(tmp_path / "missing.mp4"), str(tmp_path / "o.mp4")],
            label="doomed",
        )


# --- export stage writes progress metrics ------------------------------------


def test_export_stage_records_progress_metrics(ffmpeg_bin, clip, engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="progress-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        store.put_file("shots/0.mp4", clip)

        timeline = {
            "title": "Progress render", "format": "long",
            "width": 192, "height": 108, "style": None,
            "shots": [{"idx": 0, "asset_uri": "s3://progress-test/shots/0.mp4",
                       "origin": "own", "duration_ms": 2000, "subject": "s0"}],
        }
        import uuid

        ref = str(uuid.uuid4())
        uri = cpu_stages.export_stage(ref, timeline)
        assert uri is not None

    with Session(engine) as session:
        totals = session.exec(
            select(Metric).where(Metric.stage == "export_total", Metric.ref == ref)
        ).all()
        assert [t.duration_ms for t in totals] == [2000]
        progress = session.exec(
            select(Metric)
            .where(Metric.stage == "export_progress", Metric.ref == ref)
            .order_by(Metric.created_at)
        ).all()
        assert progress, "no progress snapshots recorded"
        assert progress[-1].duration_ms == 2000  # finish() pins the final row
        assert all(0 <= p.duration_ms <= 2000 for p in progress)


# --- the polling endpoint ----------------------------------------------------


def test_export_progress_endpoint(client, session):
    assert client.get("/metrics/exports/unknown-ref").status_code == 404

    session.add(Metric(stage="export_total", ref="board-x", duration_ms=8000))
    session.add(Metric(stage="export_progress", ref="board-x", duration_ms=2400))
    session.commit()

    body = client.get("/metrics/exports/board-x").json()
    assert body["total_ms"] == 8000
    assert body["rendered_ms"] == 2400
    assert body["pct"] == 30.0
    assert body["done"] is False

    session.add(Metric(stage="export_progress", ref="board-x", duration_ms=8000))
    session.commit()
    body = client.get("/metrics/exports/board-x").json()
    assert body["pct"] == 100.0
    assert body["done"] is True


def test_export_progress_endpoint_ignores_previous_run(client, session):
    """A re-export resets progress: snapshots older than the newest
    export_total row belong to the previous run."""
    import datetime

    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    session.add(Metric(stage="export_total", ref="board-y", duration_ms=4000, created_at=old))
    session.add(Metric(stage="export_progress", ref="board-y", duration_ms=4000, created_at=old))
    session.add(Metric(stage="export_total", ref="board-y", duration_ms=4000))
    session.commit()

    body = client.get("/metrics/exports/board-y").json()
    assert body["rendered_ms"] == 0
    assert body["done"] is False
