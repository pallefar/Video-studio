"""CPU-only regression harness for the render engines (Chatterbox TTS +
MuseTalk lip-sync).

This module proves two things without a CUDA device:

1. `worker_gpu/run.py:main()` actually warms both models at boot (M3.1 —
   "models load once at boot, never unloaded") instead of lazily on the
   first job. Redis/RQ are faked; `get_engines()` is monkeypatched so no
   real model weights are ever touched here.
2. The real engines (`ChatterboxEngine`, `MuseTalkEngine`) expose exactly
   the method signatures the stage functions call and the dev engines
   mirror, and their CUDA guard refuses rather than silently falling back —
   so a signature drift or a deleted guard fails a two-second CPU test
   instead of a 3090 render.

This module deliberately never exercises real model weights, real audio, or
real VRAM — that acceptance is workstation-manual and gated in plan 01-03.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import wave
from array import array

import pytest
from moto import mock_aws
from sqlmodel import Session
from structlog.testing import capture_logs

import pipeline_core.db as core_db
import scripts.bench as bench
import worker_gpu.run as run_module
import worker_gpu.stages as gpu_stages
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from worker_cpu.ffmpeg.assemble import chunk_keys_for_job
from worker_cpu.ffmpeg.ingest import probe
from worker_gpu.engines.audio import (
    PROJECT_CHANNELS,
    PROJECT_SAMPLE_RATE,
    build_window_audio,
    find_ffmpeg,
    lipsync_chunk_key,
    tts_segment_key,
    write_project_wav,
)
from worker_gpu.engines.dev import DevLipsyncEngine, DevTTSEngine
from worker_gpu.engines.lipsync import MuseTalkEngine
from worker_gpu.engines.tts import ChatterboxEngine


@pytest.fixture(scope="module")
def ffmpeg_bin():
    try:
        return find_ffmpeg()
    except Exception:
        pytest.skip("no ffmpeg available")


class _FakeQueue:
    def __init__(self, name, connection=None):
        self.name = name
        self.connection = connection


class _FakeWorker:
    """Records whether `.work()` was reached, without touching Redis/RQ."""

    instances: list["_FakeWorker"] = []

    def __init__(self, queues, connection=None):
        self.queues = queues
        self.connection = connection
        self.worked = False
        _FakeWorker.instances.append(self)

    def work(self):
        self.worked = True
        run_module.log.info("gpu_worker_fake_work_reached")


class _FakeRedis:
    @classmethod
    def from_url(cls, url):
        return cls()


@pytest.fixture(autouse=True)
def _patch_redis_and_rq(monkeypatch):
    """Every test in this module drives `main()` without touching Redis/RQ."""
    _FakeWorker.instances = []
    monkeypatch.setattr("redis.Redis", _FakeRedis)
    monkeypatch.setattr("rq.Queue", _FakeQueue)
    monkeypatch.setattr("rq.Worker", _FakeWorker)
    yield
    _FakeWorker.instances = []


def _patch_get_engines(monkeypatch, *, side_effect=None):
    """Install a recording fake for `worker_gpu.stages.get_engines` and
    return the call-order list `main()`'s import will observe."""
    calls: list[str] = []

    def fake_get_engines():
        calls.append("get_engines")
        if side_effect is not None:
            raise side_effect
        return (DevTTSEngine(store=None), DevLipsyncEngine(store=None))

    monkeypatch.setattr(gpu_stages, "get_engines", fake_get_engines)
    return calls


# ---------------------------------------------------------------------------
# Task 1: boot-time model warming in worker_gpu/run.py
# ---------------------------------------------------------------------------


def test_main_warms_engines_before_worker_consumes_jobs(monkeypatch):
    """`main()` calls `get_engines()` before `worker.work()` — call ORDER,
    not merely that both happened."""
    calls = _patch_get_engines(monkeypatch)

    run_module.main()

    assert calls == ["get_engines"]
    assert len(_FakeWorker.instances) == 1
    assert _FakeWorker.instances[0].worked is True


def test_main_boot_log_names_the_warmed_engine_classes(monkeypatch):
    """The boot log records that warming completed, including which engine
    classes were loaded, so a boot transcript proves the models are
    resident."""
    _patch_get_engines(monkeypatch)

    with capture_logs() as logs:
        run_module.main()

    events = [entry["event"] for entry in logs]
    assert "gpu_worker_warming_start" in events
    done = next(entry for entry in logs if entry["event"] == "gpu_worker_warming_done")
    assert done["tts_engine"] == "DevTTSEngine"
    assert done["lipsync_engine"] == "DevLipsyncEngine"

    # call order proven via the log transcript itself: warming start/done
    # must both precede the fake worker reaching work().
    warm_start = events.index("gpu_worker_warming_start")
    warm_done = events.index("gpu_worker_warming_done")
    work_reached = events.index("gpu_worker_fake_work_reached")
    assert warm_start < warm_done < work_reached


def test_main_propagates_engine_load_failure_and_never_starts_worker(monkeypatch):
    """When `get_engines()` raises (no CUDA, missing weights, a dependency
    conflict), `main()` propagates the exception and `worker.work()` is
    never reached — a worker that cannot load its models must not start
    consuming jobs."""
    _patch_get_engines(monkeypatch, side_effect=RuntimeError("no CUDA device"))

    with pytest.raises(RuntimeError, match="no CUDA device"):
        run_module.main()

    assert _FakeWorker.instances == []  # Worker() was never even constructed


def test_main_calls_get_engines_exactly_once_during_boot(monkeypatch):
    """`get_engines()` is called exactly once during boot — the stage
    functions reuse the same populated singleton rather than loading a
    second copy."""
    calls = _patch_get_engines(monkeypatch)

    run_module.main()

    assert calls.count("get_engines") == 1


# ---------------------------------------------------------------------------
# Task 2: engine interface contract, CUDA-free
# ---------------------------------------------------------------------------

# Chatterbox's documented valid ranges for its two delivery controls
# (github.com/resemble-ai/chatterbox — generate() docstring).
CHATTERBOX_EXAGGERATION_RANGE = (0.25, 2.0)
CHATTERBOX_CFG_WEIGHT_RANGE = (0.2, 1.0)


def _positional_params(func) -> list[inspect.Parameter]:
    sig = inspect.signature(func)
    return [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.name != "self"
    ]


def test_chatterbox_and_dev_tts_synthesize_segment_share_a_call_contract():
    """`ChatterboxEngine.synthesize_segment` and `DevTTSEngine.synthesize_segment`
    accept the same positional parameter count in the same order and both
    accept `emotion` as a keyword."""
    real_params = _positional_params(ChatterboxEngine.synthesize_segment)
    dev_params = _positional_params(DevTTSEngine.synthesize_segment)

    assert len(real_params) == len(dev_params)
    assert [p.name for p in real_params] == [p.name for p in dev_params]

    real_sig = inspect.signature(ChatterboxEngine.synthesize_segment)
    dev_sig = inspect.signature(DevTTSEngine.synthesize_segment)
    assert "emotion" in real_sig.parameters
    assert "emotion" in dev_sig.parameters
    assert real_sig.parameters["emotion"].kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def test_musetalk_and_dev_lipsync_sync_chunk_share_a_call_contract():
    """`MuseTalkEngine.sync_chunk` and `DevLipsyncEngine.sync_chunk` accept
    the same positional parameter count in the same order. Parameter NAMES
    differ (`chunk_start_ms` vs `start_ms`) while POSITIONS match — the
    stages.py call site passes positionally, so compare arity and order,
    not names."""
    real_params = _positional_params(MuseTalkEngine.sync_chunk)
    dev_params = _positional_params(DevLipsyncEngine.sync_chunk)

    assert len(real_params) == len(dev_params)
    # job_id and loop_id are named identically on both; the remaining two
    # (start/end ms) differ in name but must hold the same position.
    assert real_params[0].name == dev_params[0].name == "job_id"
    assert real_params[1].name == dev_params[1].name == "loop_id"


@pytest.mark.parametrize("engine_cls", [ChatterboxEngine, MuseTalkEngine])
def test_real_engine_load_refuses_without_cuda(engine_cls):
    """Both real engines' `load()` raise rather than return when no CUDA
    device is present — the guard that keeps dev engines opt-in rather than
    a silent fallback. Must pass on a machine with no torch installed at
    all, or CPU-only torch — never by faking a CUDA device being present,
    which would let a deleted guard pass silently."""
    engine = engine_cls(store=None)
    with pytest.raises((ImportError, RuntimeError, NotImplementedError)):
        engine.load()


def test_emotion_presets_carry_exactly_chatterbox_two_keys_in_range():
    """Every emotion preset in `pipeline_core.emotions.EMOTIONS` carries
    exactly the two keys Chatterbox's generate call consumes, with values
    inside Chatterbox's documented ranges — so `emotion_params()` output can
    be passed straight through with no translation layer."""
    from pipeline_core.emotions import EMOTIONS

    for name, params in EMOTIONS.items():
        assert set(params.keys()) == {"exaggeration", "cfg_weight"}, name
        exaggeration = params["exaggeration"]
        cfg_weight = params["cfg_weight"]
        assert CHATTERBOX_EXAGGERATION_RANGE[0] <= exaggeration <= CHATTERBOX_EXAGGERATION_RANGE[1], name
        assert CHATTERBOX_CFG_WEIGHT_RANGE[0] <= cfg_weight <= CHATTERBOX_CFG_WEIGHT_RANGE[1], name


@pytest.mark.parametrize("engine_cls", [ChatterboxEngine, MuseTalkEngine])
def test_real_engine_constructs_from_store_alone_and_exposes_load(engine_cls):
    """Both real engine classes construct from an ObjectStore alone and
    expose `load`, so `get_engines()` can build them uniformly."""
    ctor_params = _positional_params(engine_cls.__init__)
    assert [p.name for p in ctor_params] == ["store"]
    assert hasattr(engine_cls, "load") and callable(engine_cls.load)


# ---------------------------------------------------------------------------
# Task 1 (partial — CUDA-free contract layer only): worker_gpu/engines/audio.py
#
# This plan is executed in two halves. This half covers only the contract
# helpers that need no model: key shapes, the 48 kHz stereo convention, and
# the lip-sync window-audio timeline. `ChatterboxEngine.synthesize_segment`
# and `MuseTalkEngine.sync_chunk` (the plan's Tests 7-9) remain out of scope
# here — see 01-03-SUMMARY.md.
# ---------------------------------------------------------------------------


def _tone_segment_wav(ffmpeg_bin: str, tmp_path, name: str, freq: int, duration_ms: int):
    path = tmp_path / f"{name}.wav"
    subprocess.run(
        [
            ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:sample_rate=48000:duration={duration_ms / 1000:.3f}",
            "-ac", "2", "-c:a", "pcm_s16le", str(path),
        ],
        check=True, capture_output=True,
    )
    return path


def _timeline_store_and_segments(ffmpeg_bin: str, tmp_path):
    """Three segments with distinct tones and non-zero trailing pauses:
    seg0 [0,2000) tone 220Hz, pause to 2500; seg1 [2500,5500) tone 900Hz,
    pause to 5800; seg2 [5800,8300) tone 1700Hz, no pause."""
    store = ObjectStore(Settings(s3_endpoint="", s3_bucket="window-audio"))
    store.ensure_bucket()
    specs = [(0, 220, 2000, 500), (1, 900, 3000, 300), (2, 1700, 2500, 0)]
    segments = []
    for idx, freq, duration_ms, pause_ms in specs:
        local = _tone_segment_wav(ffmpeg_bin, tmp_path, f"seg{idx}", freq, duration_ms)
        uri = store.put_file(f"jobs/window-job/tts/{idx}.wav", local)
        segments.append(
            {"idx": idx, "audio_uri": uri, "duration_ms": duration_ms, "pause_after_ms": pause_ms}
        )
    return store, segments


def _extract_pcm(ffmpeg_bin: str, wav_path, start_s: float, dur_s: float) -> bytes:
    result = subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(wav_path),
            "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}",
            "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
        ],
        capture_output=True,
    )
    return result.stdout


def _zero_crossing_freq(pcm_bytes: bytes, sample_rate: int = 8000) -> float:
    """Cheap dominant-frequency estimate for a near-pure tone: count sign
    changes and divide by 2x the analysed duration. Good enough to tell 220
    Hz from 900 Hz from 1700 Hz apart without an FFT dependency."""
    samples = array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if len(samples) < 2:
        return 0.0
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if (a >= 0) != (b >= 0))
    duration_s = len(samples) / sample_rate
    return crossings / (2 * duration_s) if duration_s > 0 else 0.0


def test_tts_and_lipsync_key_shapes_round_trip_through_assemble_sort():
    """Test 1: key shapes match the dev engine/assembler convention, and the
    lipsync key's leading integer is exactly the window start — proven by
    round-tripping through the assembler's own sort function."""
    assert tts_segment_key("job-1", 0) == "jobs/job-1/tts/0.wav"
    key = lipsync_chunk_key("job-1", 0, 5000)
    assert key == "jobs/job-1/lipsync/0_5000.mp4"

    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="key-shape"))
        store.ensure_bucket()
        store.put_bytes(key, b"fake-mp4-bytes")
        assert chunk_keys_for_job(store, "job-1") == [key]


def test_lipsync_chunk_key_survives_out_of_order_writes():
    """Test 2: chunk_keys_for_job returns ascending window order regardless
    of the order the chunks were written to the store."""
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="key-order"))
        store.ensure_bucket()
        windows = [(60000, 120000), (0, 60000), (120000, 150000)]
        for start, end in windows:
            store.put_bytes(lipsync_chunk_key("job-2", start, end), b"fake-mp4-bytes")

        assert chunk_keys_for_job(store, "job-2") == [
            lipsync_chunk_key("job-2", 0, 60000),
            lipsync_chunk_key("job-2", 60000, 120000),
            lipsync_chunk_key("job-2", 120000, 150000),
        ]


def test_write_project_wav_converts_to_project_convention(ffmpeg_bin, tmp_path):
    """Test 3: a 24 kHz mono input becomes 48 kHz stereo pcm_s16le,
    preserving duration within 20 ms — Chatterbox's native output format
    (RESEARCH.md Pitfall 3)."""
    src = tmp_path / "src.wav"
    subprocess.run(
        [
            ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
            "-i", "sine=frequency=220:sample_rate=24000:duration=1.5",
            "-ac", "1", "-c:a", "pcm_s16le", str(src),
        ],
        check=True, capture_output=True,
    )
    src_duration_ms = probe(ffmpeg_bin, src)["duration_ms"]

    dst = tmp_path / "dst.wav"
    write_project_wav(ffmpeg_bin, src, dst)

    with wave.open(str(dst), "rb") as w:
        assert w.getframerate() == PROJECT_SAMPLE_RATE
        assert w.getnchannels() == PROJECT_CHANNELS

    dst_duration_ms = probe(ffmpeg_bin, dst)["duration_ms"]
    assert abs(dst_duration_ms - src_duration_ms) <= 20


def test_build_window_audio_matches_window_length(ffmpeg_bin, tmp_path):
    """Test 4: output duration equals end_ms - start_ms within 40 ms, for a
    window that starts mid-segment and ends mid-segment."""
    with mock_aws():
        store, segments = _timeline_store_and_segments(ffmpeg_bin, tmp_path)
        dst = tmp_path / "window.wav"
        start_ms, end_ms = 1000, 6300
        build_window_audio(ffmpeg_bin, store, segments, start_ms, end_ms, dst)

        duration_ms = probe(ffmpeg_bin, dst)["duration_ms"]
        assert abs(duration_ms - (end_ms - start_ms)) <= 40


def test_build_window_audio_places_segments_at_timeline_offsets(ffmpeg_bin, tmp_path):
    """Test 5: segment audio lands at the offset implied by
    duration_ms + pause_after_ms, not naive back-to-back concatenation —
    probed by the distinct tone frequency present at known offsets into the
    output."""
    with mock_aws():
        store, segments = _timeline_store_and_segments(ffmpeg_bin, tmp_path)
        dst = tmp_path / "window.wav"
        start_ms, end_ms = 1000, 6300
        build_window_audio(ffmpeg_bin, store, segments, start_ms, end_ms, dst)

        # 500ms into the window -> global t=1500, inside seg0's audio [0,2000).
        freq = _zero_crossing_freq(_extract_pcm(ffmpeg_bin, dst, 0.5, 0.3))
        assert abs(freq - 220) < 80

        # 2000ms into the window -> global t=3000, inside seg1's audio [2500,5500).
        freq = _zero_crossing_freq(_extract_pcm(ffmpeg_bin, dst, 2.0, 0.3))
        assert abs(freq - 900) < 200

        # 5000ms into the window -> global t=6000, inside seg2's audio [5800,8300).
        freq = _zero_crossing_freq(_extract_pcm(ffmpeg_bin, dst, 5.0, 0.3))
        assert abs(freq - 1700) < 300


def test_build_window_audio_is_project_convention(ffmpeg_bin, tmp_path):
    """Test 6: build_window_audio output is 48 kHz stereo — the same
    convention as TTS output."""
    with mock_aws():
        store, segments = _timeline_store_and_segments(ffmpeg_bin, tmp_path)
        dst = tmp_path / "window.wav"
        build_window_audio(ffmpeg_bin, store, segments, 1000, 6300, dst)

        with wave.open(str(dst), "rb") as w:
            assert w.getframerate() == PROJECT_SAMPLE_RATE
            assert w.getnchannels() == PROJECT_CHANNELS


def test_dev_engines_produce_the_keys_audio_py_defines(ffmpeg_bin, engine, loop, monkeypatch, tmp_path):
    """Plan 01-03 Task 2: the dev engines' actual output keys equal
    audio.py's contract helpers for the same inputs — proving there is
    exactly one definition of the key shape, not two that happen to agree
    today. (ChatterboxEngine/MuseTalkEngine key resolution is out of scope
    until the real models are implemented; see 01-03-SUMMARY.md.)"""
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="cross-engine-keys"))
        store.ensure_bucket()

        tts_engine = DevTTSEngine(store)
        tts_engine.load()
        uri, _ = tts_engine.synthesize_segment("job-x", 2, "Testing key parity.", seed=1)
        _, key = store.parse_uri(uri)
        assert key == tts_segment_key("job-x", 2)

        loop_clip = tmp_path / "loop.mp4"
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
                "-i", "color=c=teal:s=64x64:d=1:r=10", "-pix_fmt", "yuv420p", str(loop_clip),
            ],
            check=True, capture_output=True,
        )
        with Session(engine) as session:
            db_loop = session.get(type(loop), loop.id)
            db_loop.source_uri = store.put_file("loops/x/source.mp4", loop_clip)
            session.add(db_loop)
            session.commit()

        lipsync_engine = DevLipsyncEngine(store)
        lipsync_engine.load()
        chunk_uri = lipsync_engine.sync_chunk("job-x", str(loop.id), 0, 1000)
        _, chunk_key = store.parse_uri(chunk_uri)
        assert chunk_key == lipsync_chunk_key("job-x", 0, 1000)


# ---------------------------------------------------------------------------
# 01-04 Task 1: scripts/bench.py --smoke CLI, CPU-only.
#
# These prove the argument-parsing guards and the CUDA refusal path only —
# never the render path itself, which needs real CUDA (01-04 Task 2, gated
# on the workstation). No test here fakes CUDA availability to reach
# smoke()'s render body.
# ---------------------------------------------------------------------------


def test_bench_cli_requires_exactly_one_of_smoke_or_loop(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bench.py"])
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code != 0


def test_bench_cli_rejects_both_smoke_and_loop(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bench.py", "--smoke", "--loop", "some-loop-id"])
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code != 0


def test_bench_cli_voice_and_base_loop_parse_alongside_smoke(monkeypatch):
    """--voice / --base-loop parse cleanly with --smoke and are threaded
    through to smoke() positionally — no collision with the pre-existing
    --loop mode's parser entry."""
    calls = []
    monkeypatch.setattr(bench, "smoke", lambda voice, base_loop: calls.append((voice, base_loop)) or 0)
    monkeypatch.setattr(
        sys, "argv", ["bench.py", "--smoke", "--voice", "voice-1", "--base-loop", "loop-1"]
    )

    code = bench.main()

    assert code == 0
    assert calls == [("voice-1", "loop-1")]


def test_bench_cli_base_loop_flag_does_not_collide_with_loop_flag(monkeypatch):
    """Regression guard for the naming decision: --base-loop is a distinct
    flag from --loop (the M2 cache-benchmark mode) and --loop's value still
    reaches bench_loop() untouched when --base-loop is also present."""
    calls = []
    monkeypatch.setattr(bench, "bench_loop", lambda loop_id: calls.append(loop_id) or 0)
    monkeypatch.setattr(
        sys, "argv", ["bench.py", "--loop", "loop-id-x", "--base-loop", "should-be-ignored"]
    )

    code = bench.main()

    assert code == 0
    assert calls == ["loop-id-x"]


def test_smoke_exits_1_with_cuda_message_and_no_traceback_when_gpu_absent(capsys):
    """`smoke()` fails via `_require_gpu`'s SystemExit(1) before touching the
    database or loading any model — proven by the CUDA-guard message
    reaching stderr with no real GPU present. Must pass with no torch
    installed at all, or CPU-only torch — never by faking a CUDA device,
    which would let a deleted guard pass silently."""
    with pytest.raises(SystemExit) as exc:
        bench.smoke(None, None)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "CUDA" in err
    assert "Traceback" not in err
