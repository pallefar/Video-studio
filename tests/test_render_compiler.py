"""M16: timeline -> ffmpeg compiler. Golden graph shapes need no ffmpeg;
the end-to-end render and the C1 frame-sampling test run against the static
ffmpeg binary (imageio-ffmpeg) and are skipped only where none exists."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session, select

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Asset, AssetOrigin, Project, ProjectAsset, Storyboard
from worker_cpu.ffmpeg.compiler import build_ffmpeg_args, watermark_required
from worker_cpu.ffmpeg.overlay import make_watermark_png


def _timeline(origins: list[str], width=1920, height=1080, transition_ms=0, durations=None):
    durations = durations or [5000] * len(origins)
    return {
        "storyboard_id": "sb",
        "title": "Test export",
        "format": "long",
        "width": width,
        "height": height,
        "style": None,
        "transition_ms": transition_ms,
        "shots": [
            {"idx": i, "asset_uri": f"s3://b/{i}.mp4", "origin": origin, "duration_ms": d, "subject": f"s{i}"}
            for i, (origin, d) in enumerate(zip(origins, durations))
        ],
    }


def _graph(args: list[str]) -> str:
    return args[args.index("-filter_complex") + 1]


# --- Golden graph shapes ---------------------------------------------------


def test_single_shot_graph():
    args = build_ffmpeg_args(_timeline(["own"]), ["a.mp4"], "out.mp4", None)
    graph = _graph(args)
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in graph
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2" in graph
    assert "concat" not in graph and "xfade" not in graph
    assert args[args.index("-map") + 1] == "[v0]"
    assert "-crf" in args and args[args.index("-crf") + 1] == "18"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "+faststart" in args


def test_multi_shot_hard_cut_concat():
    args = build_ffmpeg_args(_timeline(["own", "stock", "own"]), ["a", "b", "c"], "o.mp4", None)
    assert "[v0][v1][v2]concat=n=3:v=1:a=0[vcat]" in _graph(args)


def test_xfade_chain_offsets():
    timeline = _timeline(["own", "own", "own"], transition_ms=500, durations=[5000, 4000, 3000])
    args = build_ffmpeg_args(timeline, ["a", "b", "c"], "o.mp4", None)
    graph = _graph(args)
    assert "[v0][v1]xfade=transition=fade:duration=0.500:offset=4.500[x1]" in graph
    assert "[x1][v2]xfade=transition=fade:duration=0.500:offset=8.000[x2]" in graph
    # total duration shrinks by (n-1) * transition
    assert args[-2] == "11.000"


def test_short_format_dimensions():
    args = build_ffmpeg_args(_timeline(["own"], width=1080, height=1920), ["a"], "o.mp4", None)
    assert "scale=1080:1920" in _graph(args)


def test_silent_bed_when_no_audio_sources():
    args = build_ffmpeg_args(_timeline(["own", "own"]), ["a", "b"], "o.mp4", None)
    graph = _graph(args)
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in graph
    audio_map = args[args.index("-map", args.index("-map") + 2) + 1]
    assert audio_map == "[aout]"


# --- C1: the watermark decision has no off-switch --------------------------


def test_watermark_injected_for_generated_content():
    timeline = _timeline(["own", "generated"])
    assert watermark_required(timeline)
    args = build_ffmpeg_args(timeline, ["a", "b"], "o.mp4", "wm.png")
    graph = _graph(args)
    assert "overlay=W-w-24:H-h-24" in graph
    assert "enable=" not in graph  # full duration, never a timed window
    assert "wm.png" in args


def test_no_watermark_for_clean_footage():
    args = build_ffmpeg_args(_timeline(["own", "stock"]), ["a", "b"], "o.mp4", None)
    assert "overlay" not in _graph(args)


def test_generated_content_without_overlay_refuses_to_compile():
    with pytest.raises(ValueError, match="C1"):
        build_ffmpeg_args(_timeline(["generated"]), ["a"], "o.mp4", None)


# --- Real renders (static ffmpeg) ------------------------------------------


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def clips(ffmpeg_bin, tmp_path_factory) -> list[Path]:
    tmp = tmp_path_factory.mktemp("clips")
    paths = []
    for name, colour in [("red", "red"), ("blue", "blue")]:
        path = tmp / f"{name}.mp4"
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
             "-i", f"color=c={colour}:s=192x108:d=1.2:r=25",
             "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        paths.append(path)
    return paths


def _render(ffmpeg_bin, timeline, clips, out_dir: Path, name: str) -> Path:
    overlay = None
    if watermark_required(timeline):
        overlay = str(make_watermark_png(out_dir / f"{name}-wm.png", timeline["width"], timeline["height"]))
    output = out_dir / f"{name}.mp4"
    args = build_ffmpeg_args(timeline, [str(c) for c in clips], str(output), overlay, ffmpeg_bin=ffmpeg_bin)
    subprocess.run(args, check=True, capture_output=True)
    assert output.stat().st_size > 1000
    return output


def _frame(ffmpeg_bin, video: Path, at_s: float, out_png: Path):
    from PIL import Image

    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-ss", f"{at_s:.2f}", "-i", str(video),
         "-frames:v", "1", str(out_png)],
        check=True, capture_output=True,
    )
    return Image.open(out_png).convert("L")


def test_real_render_and_c1_frame_sampling(ffmpeg_bin, clips, tmp_path):
    """M5's frame-sampling requirement, applied to studio renders: watermark
    pixels present at 10%, 50% and 90% of duration."""
    durations = [1000, 1000]
    marked = _render(
        ffmpeg_bin,
        _timeline(["generated", "own"], width=192, height=108, durations=durations),
        clips, tmp_path, "marked",
    )
    clean = _render(
        ffmpeg_bin,
        _timeline(["own", "own"], width=192, height=108, durations=durations),
        clips, tmp_path, "clean",
    )

    total_s = sum(durations) / 1000
    for fraction in (0.1, 0.5, 0.9):
        at = total_s * fraction
        frame_marked = _frame(ffmpeg_bin, marked, at, tmp_path / f"m{fraction}.png")
        frame_clean = _frame(ffmpeg_bin, clean, at, tmp_path / f"c{fraction}.png")
        pixels = frame_marked.size[0] * frame_marked.size[1]
        changed = sum(
            1 for a, b in zip(frame_marked.getdata(), frame_clean.getdata()) if abs(a - b) > 30
        )
        assert changed / pixels > 0.005, f"watermark not detectable at {fraction:.0%} of duration"


def test_export_stage_renders_and_files_asset(ffmpeg_bin, clips, engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="render-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)

        for i, clip in enumerate(clips):
            store.put_file(f"shots/{i}.mp4", clip)

        with Session(engine) as session:
            project = Project(title="Render project")
            session.add(project)
            session.commit()
            board = Storyboard(title="Render board", project_id=project.id)
            session.add(board)
            session.commit()
            board_id, project_id = str(board.id), project.id

        timeline = {
            "storyboard_id": board_id, "title": "Render board", "format": "long",
            "width": 192, "height": 108, "style": None,
            "shots": [
                {"idx": i, "asset_uri": f"s3://render-test/shots/{i}.mp4",
                 "origin": "generated" if i == 0 else "own",
                 "duration_ms": 1000, "subject": f"s{i}"}
                for i in range(len(clips))
            ],
        }
        uri = cpu_stages.export_stage(board_id, timeline)
        assert uri == f"s3://render-test/renders/{board_id}/final.mp4"
        assert len(store.get_bytes(f"renders/{board_id}/final.mp4")) > 1000

    with Session(engine) as session:
        exported = session.exec(select(Asset).where(Asset.uri == uri)).one()
        assert exported.origin == AssetOrigin.generated  # contains generated material
        assert exported.approved is False
        links = session.exec(select(ProjectAsset).where(ProjectAsset.asset_id == exported.id)).all()
        assert [link.project_id for link in links] == [project_id]
