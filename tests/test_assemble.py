"""M4/M5 acceptance: the assembly chain end to end with real ffmpeg —
two-pass loudnorm to -14 LUFS, chunk concat, caption burn-in, b-roll
insertion, C1 watermark frame-sampled at 10/50/90%, and a C3 encode-chain
probe: near-ultrasonic audio content (where Chatterbox's watermark lives)
survives loudnorm + AAC 192k."""

from __future__ import annotations

import math
import subprocess
import uuid
import wave
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    BaseLoop,
    JobStatus,
    RenderJob,
    Segment,
    VoiceProfile,
)
from worker_cpu.ffmpeg.assemble import (
    build_assemble_args,
    build_voice_args,
    chunk_keys_for_job,
    measure_loudness,
)
from worker_cpu.ffmpeg.captions import CaptionLine, caption_lines, even_split_timings

WIDTH, HEIGHT = 192, 108  # small frames keep the real renders fast


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def media(ffmpeg_bin, tmp_path_factory):
    """Two 1 s red/blue silent chunks + two 1 s wavs. The wavs carry a 440 Hz
    voice-band tone plus a -25 dB 17.5 kHz tone standing in for Chatterbox's
    inaudible watermark (C3)."""
    tmp = tmp_path_factory.mktemp("assemble-media")
    chunks = []
    for name, colour in [("0_1000", "red"), ("1000_2000", "blue")]:
        path = tmp / f"{name}.mp4"
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
             "-i", f"color=c={colour}:s={WIDTH}x{HEIGHT}:d=1:r=25",
             "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        chunks.append(path)
    wavs = []
    for n in range(2):
        path = tmp / f"seg_{n}.wav"
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
             "-i", "sine=frequency=440:sample_rate=48000:duration=1",
             "-f", "lavfi", "-i", "sine=frequency=17500:sample_rate=48000:duration=1",
             "-filter_complex",
             "[0:a]volume=0.4[v];[1:a]volume=0.056[w];[v][w]amix=inputs=2:normalize=0[a]",
             "-map", "[a]", "-c:a", "pcm_s16le", str(path)],
            check=True, capture_output=True,
        )
        wavs.append(path)
    return {"chunks": chunks, "wavs": wavs}


def _goertzel_power(samples: list[float], sample_rate: int, freq: float) -> float:
    """Detect one frequency without numpy — plenty for a pass/fail probe."""
    n = len(samples)
    k = int(0.5 + n * freq / sample_rate)
    omega = 2 * math.pi * k / n
    coeff = 2 * math.cos(omega)
    s_prev = s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2, s_prev = s_prev, s
    return s_prev2**2 + s_prev**2 - coeff * s_prev * s_prev2


def _tone_present(ffmpeg_bin, video: Path, tmp: Path, freq: float) -> bool:
    wav = tmp / "decoded.wav"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True,
    )
    with wave.open(str(wav)) as reader:
        raw = reader.readframes(48000)  # 1 s window
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) / 32768
        for i in range(0, len(raw), 2)
    ]
    signal = _goertzel_power(samples, 48000, freq)
    floor = _goertzel_power(samples, 48000, freq + 1700)  # nearby empty bin
    return signal > floor * 10


# --- pure pieces -------------------------------------------------------------


def test_even_split_timings_track_segment_clock():
    words = even_split_timings(
        [{"text": "one two", "duration_ms": 1000, "pause_after_ms": 500},
         {"text": "three", "duration_ms": 800, "pause_after_ms": 0}]
    )
    assert [w.text for w in words] == ["one", "two", "three"]
    assert (words[0].start_ms, words[0].end_ms) == (0, 500)
    assert (words[1].start_ms, words[1].end_ms) == (500, 1000)
    assert (words[2].start_ms, words[2].end_ms) == (1500, 2300)  # pause honoured


def test_caption_lines_group_and_span():
    words = even_split_timings([{"text": "a b c d e f", "duration_ms": 600, "pause_after_ms": 0}])
    lines = caption_lines(words, max_chars=5)
    assert [l.text for l in lines] == ["a b c", "d e f"]
    assert lines[0].start_ms == 0 and lines[1].end_ms == 600


def test_voice_args_include_pauses():
    args = build_voice_args(["a.wav", "b.wav"], [300, 0], "out.wav")
    graph = args[args.index("-filter_complex") + 1]
    assert "atrim=0:0.300[p0]" in graph
    assert "concat=n=3:v=0:a=1[voice]" in graph  # s0 + p0 + s1


def test_assemble_args_order_watermark_last():
    line = CaptionLine("hello", 0, 500)
    args = build_assemble_args(
        ["c0.mp4"], "voice.wav", "wm.png", "out.mp4",
        captions=[line], caption_pngs=["cap.png"],
        broll=[{"path": "b.mp4", "start_ms": 0, "end_ms": 400}], total_ms=2000,
    )
    graph = args[args.index("-filter_complex") + 1]
    # order: b-roll -> caption -> watermark; C1 overlay carries no enable=
    assert graph.index("eof_action=pass") < graph.index("H*0.88")
    wm_clause = graph.split(";")[-1]
    assert "overlay=W-w-24:H-h-24[vout]" in wm_clause and "enable" not in wm_clause
    assert "-crf" in args and args[args.index("-crf") + 1] == "18"


def test_chunk_keys_sorted_by_window_start():
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="chunk-test"))
        store.ensure_bucket()
        for key in ["jobs/j/lipsync/90000_180000.mp4", "jobs/j/lipsync/0_90000.mp4",
                    "jobs/j/lipsync/180000_200000.mp4"]:
            store.put_bytes(key, b"x")
        keys = chunk_keys_for_job(store, "j")
        assert [k.rsplit("/", 1)[-1] for k in keys] == [
            "0_90000.mp4", "90000_180000.mp4", "180000_200000.mp4"
        ]


# --- the full chain against real ffmpeg --------------------------------------


@pytest.fixture()
def assembled(ffmpeg_bin, media, engine, monkeypatch, tmp_path):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="assemble-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)

        with Session(engine) as session:
            voice = VoiceProfile(name="karsten", reference_audio_uri="s3://t/v.wav")
            loop = BaseLoop(name="desk", source_uri="s3://t/l.mp4", fps=25.0, frame_count=750)
            session.add(voice)
            session.add(loop)
            session.commit()
            job = RenderJob(
                title="assembly e2e", script="Rockets are loud. Space is silent.",
                voice_profile_id=voice.id, base_loop_id=loop.id,
                status=JobStatus.assemble,
            )
            session.add(job)
            session.commit()
            job_id = str(job.id)

            for idx, (text, wav) in enumerate(
                zip(["Rockets are loud.", "Space is silent."], media["wavs"])
            ):
                key = f"jobs/{job_id}/tts/{idx}.wav"
                store.put_file(key, wav)
                session.add(Segment(
                    job_id=job.id, idx=idx, text=text, pause_after_ms=0,
                    audio_uri=store.uri_for(key), duration_ms=1000, seed=1,
                ))
            session.commit()

        for chunk in media["chunks"]:
            store.put_file(f"jobs/{job_id}/lipsync/{chunk.stem}.mp4", chunk)

        cpu_stages.assemble_stage(job_id)

        final = tmp_path / "final.mp4"
        final.write_bytes(store.get_bytes(f"jobs/{job_id}/final.mp4"))
        yield {"engine": engine, "job_id": job_id, "final": final, "store": store}


def test_assemble_end_to_end(assembled, ffmpeg_bin, tmp_path):
    engine, job_id, final = assembled["engine"], assembled["job_id"], assembled["final"]
    assert final.stat().st_size > 1000

    with Session(engine) as session:
        job = session.get(RenderJob, uuid.UUID(job_id))
        assert job.status == JobStatus.review  # assembled -> human review gate
        assert job.output_uri.endswith(f"jobs/{job_id}/final.mp4")

    # loudness: output voice must sit at YouTube's -14 LUFS target
    measured = measure_loudness(str(final), ffmpeg_bin)
    assert abs(float(measured["input_i"]) - (-14.0)) < 1.5, measured["input_i"]

    # C3 proxy: the near-ultrasonic band survived loudnorm + AAC 192k
    assert _tone_present(ffmpeg_bin, final, tmp_path, 17500)


def test_c1_watermark_frame_sampling(assembled, ffmpeg_bin, tmp_path):
    """M5: watermark pixels present at 10/50/90% of duration — sampled on the
    real assembled output, bottom-right corner vs the flat chunk colour."""
    from PIL import Image

    final = assembled["final"]
    for fraction in (0.1, 0.5, 0.9):
        png = tmp_path / f"f{fraction}.png"
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-ss", f"{2.0 * fraction:.2f}",
             "-i", str(final), "-frames:v", "1", str(png)],
            check=True, capture_output=True,
        )
        frame = Image.open(png).convert("L")
        w, h = frame.size
        corner = frame.crop((w // 2, h // 2, w, h))  # bottom-right quadrant
        pixels = list(corner.getdata())
        spread = max(pixels) - min(pixels)
        assert spread > 40, f"no watermark contrast at {fraction:.0%} (spread {spread})"


def test_broll_inserted_when_resolver_matches(ffmpeg_bin, media, engine, monkeypatch):
    """A library asset matching a segment's text is cut in at that segment's
    beat while the voice continues — asserted by frame colour mid-overlay."""
    from pipeline_core.embeddings import get_embedder

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="broll-test"))
        store.ensure_bucket()
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)

        import subprocess as sp
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            green = Path(tmp) / "green.mp4"
            sp.run(
                [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
                 "-i", f"color=c=green:s={WIDTH}x{HEIGHT}:d=1:r=25",
                 "-pix_fmt", "yuv420p", str(green)],
                check=True, capture_output=True,
            )
            broll_key = "assets/broll/green.mp4"
            store.put_file(broll_key, green)

        with Session(engine) as session:
            voice = VoiceProfile(name="k", reference_audio_uri="s3://t/v.wav")
            loop = BaseLoop(name="d", source_uri="s3://t/l.mp4", fps=25.0, frame_count=1)
            session.add(voice)
            session.add(loop)
            session.commit()
            text = "Rockets are loud."
            session.add(Asset(
                origin=AssetOrigin.stock, uri=store.uri_for(broll_key), caption=text,
                duration_ms=1000, has_identifiable_people=False, approved=True,
                license="Pexels", source_url="https://example.com",
                embedding=get_embedder().embed(text),
            ))
            job = RenderJob(
                title="broll e2e", script=text,
                voice_profile_id=voice.id, base_loop_id=loop.id, status=JobStatus.assemble,
            )
            session.add(job)
            session.commit()
            job_id = str(job.id)
            key = f"jobs/{job_id}/tts/0.wav"
            store.put_file(key, media["wavs"][0])
            session.add(Segment(job_id=job.id, idx=0, text=text, pause_after_ms=0,
                                audio_uri=store.uri_for(key), duration_ms=1000, seed=1))
            session.commit()

        store.put_file(f"jobs/{job_id}/lipsync/0_1000.mp4", media["chunks"][0])
        cpu_stages.assemble_stage(job_id)

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "final.mp4"
            final.write_bytes(store.get_bytes(f"jobs/{job_id}/final.mp4"))
            png = Path(tmp) / "mid.png"
            subprocess.run(
                [ffmpeg_bin, "-y", "-hide_banner", "-ss", "0.5", "-i", str(final),
                 "-frames:v", "1", str(png)],
                check=True, capture_output=True,
            )
            from PIL import Image

            r, g, b = Image.open(png).convert("RGB").resize((1, 1)).getpixel((0, 0))
            assert g > r + 50, f"b-roll frame not green: rgb=({r},{g},{b})"
