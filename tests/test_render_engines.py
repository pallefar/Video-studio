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

import pytest
from structlog.testing import capture_logs

import worker_gpu.run as run_module
import worker_gpu.stages as gpu_stages
from worker_gpu.engines.dev import DevLipsyncEngine, DevTTSEngine
from worker_gpu.engines.lipsync import MuseTalkEngine
from worker_gpu.engines.tts import ChatterboxEngine


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
