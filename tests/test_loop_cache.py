"""M2 (GPU half) acceptance: MuseTalk's own preparation cache is bridged to
ObjectStore, dispatched automatically from CPU preprocessing, and both
BaseLoop cache columns are written only after every upload lands. Every test
here runs on this CUDA-less Mac: moto for S3, in-memory SQLite for the DB,
and a fake preparer standing in for the one seam where CUDA would enter."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from moto import mock_aws
from sqlmodel import Session

import pipeline_core.db as core_db
import worker_cpu.stages as cpu_stages
import worker_gpu.preprocess.loop_cache as lc
import worker_gpu.stages as gpu_stages
from pipeline_core.locks import HOLDER_RENDER, GpuLockHeld
from pipeline_core.queues import QUEUE_GPU
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import BaseLoop
from tests.conftest import RecordingDispatcher


class FakePreparer:
    """Stands in for the resident engine's prepare_loop_cache seam."""

    def __init__(self, *, write_mask=False, write_frames=False, fail=False, calls_raise=False):
        self.calls: list[tuple[Path, Path]] = []
        self.write_mask = write_mask
        self.write_frames = write_frames
        self.fail = fail
        self.calls_raise = calls_raise

    def __call__(self, source_path: Path, out_dir: Path) -> None:
        if self.calls_raise:
            raise AssertionError("preparer must not be invoked on a cache hit")
        self.calls.append((source_path, out_dir))
        if self.fail:
            raise RuntimeError("prepare failed")
        (out_dir / lc.COORDS_FILENAME).write_bytes(b"coords-bytes")
        (out_dir / lc.LATENTS_FILENAME).write_bytes(b"latents-bytes")
        if self.write_mask:
            (out_dir / lc.MASK_COORDS_FILENAME).write_bytes(b"mask-bytes")
        if self.write_frames:
            full = out_dir / "full_imgs"
            full.mkdir()
            (full / "0001.png").write_bytes(b"png")
            mask_dir = out_dir / "mask"
            mask_dir.mkdir()
            (mask_dir / "0001.png").write_bytes(b"mask-png")


class _FakeEngine:
    def __init__(self, preparer):
        self.prepare_loop_cache = preparer


class _RaisingStore:
    """Wraps a real store; raises once put_file has been called `fail_after`
    times — proves columns stay null unless every upload succeeds."""

    def __init__(self, inner: ObjectStore, fail_after: int):
        self._inner = inner
        self._count = 0
        self._fail_after = fail_after

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def put_file(self, key, path):
        self._count += 1
        if self._count >= self._fail_after:
            raise RuntimeError("simulated upload failure")
        return self._inner.put_file(key, path)


def _make_loop(session: Session, store: ObjectStore, name: str = "desk") -> str:
    key = f"loops/src/{name}.mp4"
    store.put_bytes(key, b"source-video-bytes")
    loop = BaseLoop(name=name, source_uri=store.uri_for(key), fps=25.0, frame_count=100)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    return str(loop.id)


@pytest.fixture()
def store_env(engine, monkeypatch):
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="loop-cache-test"))
        store.ensure_bucket()
        monkeypatch.setattr(gpu_stages, "ObjectStore", lambda: store)
        monkeypatch.setattr(cpu_stages, "ObjectStore", lambda: store)
        yield store


# --- build_loop_cache: the ObjectStore bridge --------------------------------


def test_build_is_noop_when_cache_present(store_env, engine, session):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer())  # first real build

    raising_preparer = FakePreparer(calls_raise=True)
    built_again = lc.build_loop_cache(store_env, loop_id, raising_preparer)

    assert built_again is False
    assert raising_preparer.calls == []


def test_build_hands_preparer_real_source_and_scratch_dir(store_env, engine, session):
    loop_id = _make_loop(session, store_env)
    captured: dict = {}

    def preparer(source_path: Path, out_dir: Path) -> None:
        captured["source_bytes"] = source_path.read_bytes()
        captured["out_dir"] = out_dir
        captured["out_dir_was_empty"] = not any(out_dir.iterdir())
        (out_dir / lc.COORDS_FILENAME).write_bytes(b"c")
        (out_dir / lc.LATENTS_FILENAME).write_bytes(b"l")

    lc.build_loop_cache(store_env, loop_id, preparer)

    assert captured["source_bytes"] == b"source-video-bytes"
    assert captured["out_dir_was_empty"] is True
    assert not captured["out_dir"].exists()  # scratch reclaimed on return


def test_build_does_not_persist_frame_images(store_env, engine, session):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer(write_frames=True))

    keys = store_env.list_keys(lc.cache_prefix(loop_id))
    assert not any(k.endswith(".png") for k in keys)
    assert not any("full_imgs" in k or "/mask/" in k for k in keys)


def test_build_mask_coords_optional(store_env, engine, session):
    loop_without = _make_loop(session, store_env, name="no-mask")
    lc.build_loop_cache(store_env, loop_without, FakePreparer())
    assert not store_env.exists(lc.mask_coords_key(loop_without))
    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_without))
        assert loop.latents_uri and loop.bbox_uri

    loop_with = _make_loop(session, store_env, name="with-mask")
    lc.build_loop_cache(store_env, loop_with, FakePreparer(write_mask=True))
    assert store_env.exists(lc.mask_coords_key(loop_with))


def test_build_leaves_columns_null_on_partial_upload_failure(store_env, engine, session):
    loop_id = _make_loop(session, store_env)
    raising_store = _RaisingStore(store_env, fail_after=2)  # fails on the final required upload

    with pytest.raises(RuntimeError):
        lc.build_loop_cache(raising_store, loop_id, FakePreparer())

    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.latents_uri is None
        assert loop.bbox_uri is None


def test_key_helpers_match_option_a_layout():
    assert lc.latents_key("L") == "loops/L/cache/latents.pt"
    assert lc.coords_key("L") == "loops/L/cache/bbox/coords.pkl"
    assert lc.mask_coords_key("L") == "loops/L/cache/bbox/mask_coords.pkl"
    assert lc.bbox_prefix("L") == "loops/L/cache/bbox"


# --- worker_gpu.stages.loop_cache_stage: dispatch, locking, idempotency -----


def test_stage_builds_cache_end_to_end_under_render_lock(
    store_env, engine, session, monkeypatch, fake_gpu_redis
):
    from pipeline_core import locks

    loop_id = _make_loop(session, store_env)
    preparer = FakePreparer()
    holder_calls: list[str] = []
    original_gpu_lock = locks.gpu_lock

    def spy_gpu_lock(redis, holder, ttl_s=locks.DEFAULT_TTL_S):
        holder_calls.append(holder)
        return original_gpu_lock(redis, holder, ttl_s)

    monkeypatch.setattr(gpu_stages, "gpu_lock", spy_gpu_lock)
    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (None, _FakeEngine(preparer)))

    gpu_stages.loop_cache_stage(loop_id)

    assert holder_calls == [HOLDER_RENDER]
    assert fake_gpu_redis._store == {}  # released after the build
    assert preparer.calls  # the preparer was genuinely invoked

    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.latents_uri and loop.bbox_uri
        _, key = store_env.parse_uri(loop.latents_uri)
        assert store_env.exists(key)
        assert store_env.exists(lc.coords_key(loop_id))


def test_stage_skips_lock_and_preparer_on_noop(store_env, engine, session, monkeypatch, fake_gpu_redis):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer())  # pre-cache it

    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: fake_gpu_redis)
    monkeypatch.setattr(gpu_stages, "_engines", (None, _FakeEngine(FakePreparer(calls_raise=True))))

    gpu_stages.loop_cache_stage(loop_id)  # must not raise (preparer would if invoked)

    assert fake_gpu_redis._store == {}  # lock never entered


def test_stage_propagates_gpu_lock_held(store_env, engine, session, monkeypatch):
    loop_id = _make_loop(session, store_env)

    def raising_gpu_lock(redis, holder, ttl_s=3600):
        raise GpuLockHeld("wan")

    monkeypatch.setattr(gpu_stages, "gpu_lock", raising_gpu_lock)
    monkeypatch.setattr(gpu_stages, "get_redis", lambda *a, **kw: object())
    monkeypatch.setattr(gpu_stages, "_engines", (None, _FakeEngine(FakePreparer())))

    with pytest.raises(GpuLockHeld):
        gpu_stages.loop_cache_stage(loop_id)

    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.latents_uri is None
        assert loop.bbox_uri is None


def test_stage_skips_loudly_when_engine_exposes_no_preparer(store_env, engine, session, monkeypatch):
    """DEV_ENGINES=1 / Phase 1 not yet landed: DevLipsyncEngine has no
    prepare_loop_cache attribute — this must stay a warning, not a crash."""
    loop_id = _make_loop(session, store_env)

    class _NoPreparerEngine:
        pass

    monkeypatch.setattr(gpu_stages, "_engines", (None, _NoPreparerEngine()))

    gpu_stages.loop_cache_stage(loop_id)  # must not raise

    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert loop.latents_uri is None
        assert loop.bbox_uri is None


# --- worker_cpu.stages.loop_preprocess_stage: the dispatch chain -----------


@pytest.fixture(scope="module")
def ffmpeg_bin():
    binary = cpu_stages._find_ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg available")
    return binary


@pytest.fixture(scope="module")
def clean_clip(ffmpeg_bin, tmp_path_factory):
    import subprocess

    tmp = tmp_path_factory.mktemp("loop-cache-clean-clip")
    clip = tmp / "clean.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", "color=c=red:s=192x108:d=1:r=25", "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    return clip


@pytest.fixture(scope="module")
def vfr_clip(ffmpeg_bin, tmp_path_factory):
    import subprocess

    tmp = tmp_path_factory.mktemp("loop-cache-vfr-clip")
    clip = tmp / "vfr.mp4"
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-f", "lavfi",
         "-i", "testsrc=size=192x108:rate=25:duration=1",
         "-vf", "select='not(mod(n,5))+not(mod(n,7))'", "-vsync", "vfr",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    return clip


def test_chain_fires_on_success(store_env, engine, session, clean_clip, monkeypatch):
    import pipeline_core.dispatch as core_dispatch

    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(core_dispatch, "Dispatcher", lambda *a, **kw: dispatcher)

    key = "loops/src/clean.mp4"
    store_env.put_file(key, clean_clip)
    loop = BaseLoop(name="clean", source_uri=store_env.uri_for(key), fps=25.0, frame_count=25)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    loop_id = str(loop.id)

    cpu_stages.loop_preprocess_stage(loop_id)

    assert dispatcher.calls == [
        (QUEUE_GPU, "worker_gpu.stages.loop_cache_stage", (loop_id,), f"{loop_id}-loop_cache")
    ]


def test_chain_does_not_fire_on_vfr_rejection(store_env, engine, session, vfr_clip, monkeypatch):
    import pipeline_core.dispatch as core_dispatch

    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(core_dispatch, "Dispatcher", lambda *a, **kw: dispatcher)

    key = "loops/src/vfr.mp4"
    store_env.put_file(key, vfr_clip)
    loop = BaseLoop(name="vfr", source_uri=store_env.uri_for(key), fps=25.0, frame_count=25)
    session.add(loop)
    session.commit()
    session.refresh(loop)
    loop_id = str(loop.id)

    cpu_stages.loop_preprocess_stage(loop_id)

    with Session(engine) as check:
        checked = check.get(BaseLoop, uuid.UUID(loop_id))
        assert checked.error is not None and "VFR" in checked.error

    assert dispatcher.calls == []


# --- the ping-pong idempotent exit also chains (Task 3) --------------------


def _make_ping_pong_loop(session: Session, store: ObjectStore, *, error=None, latents_uri=None) -> str:
    key = "loops/src/pp.mp4"
    store.put_bytes(key, b"pp-bytes")
    loop = BaseLoop(
        name="pp", source_uri=store.uri_for(key), fps=25.0, frame_count=50,
        ping_pong=True, error=error, latents_uri=latents_uri,
    )
    session.add(loop)
    session.commit()
    session.refresh(loop)
    return str(loop.id)


def test_pingpong_exit_chains_when_cache_missing(store_env, engine, session, monkeypatch):
    import pipeline_core.dispatch as core_dispatch

    monkeypatch.setattr(cpu_stages, "_find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(core_dispatch, "Dispatcher", lambda *a, **kw: dispatcher)

    loop_id = _make_ping_pong_loop(session, store_env)
    cpu_stages.loop_preprocess_stage(loop_id)

    assert dispatcher.calls == [
        (QUEUE_GPU, "worker_gpu.stages.loop_cache_stage", (loop_id,), f"{loop_id}-loop_cache")
    ]


def test_pingpong_exit_does_not_chain_with_live_cache(store_env, engine, session, monkeypatch):
    import pipeline_core.dispatch as core_dispatch

    monkeypatch.setattr(cpu_stages, "_find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(core_dispatch, "Dispatcher", lambda *a, **kw: dispatcher)

    loop_id = _make_ping_pong_loop(
        session, store_env, latents_uri="s3://loop-cache-test/loops/x/cache/latents.pt"
    )
    cpu_stages.loop_preprocess_stage(loop_id)

    assert dispatcher.calls == []


def test_pingpong_exit_does_not_chain_with_error(store_env, engine, session, monkeypatch):
    import pipeline_core.dispatch as core_dispatch

    monkeypatch.setattr(cpu_stages, "_find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(core_dispatch, "Dispatcher", lambda *a, **kw: dispatcher)

    loop_id = _make_ping_pong_loop(session, store_env, error="some prior error")
    cpu_stages.loop_preprocess_stage(loop_id)

    assert dispatcher.calls == []


# --- load_loop_cache: the reverse bridge, and the stale-column case --------


def test_load_loop_cache_round_trips_bytes(store_env, engine, session, tmp_path):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer(write_mask=True))

    dest = tmp_path / "restored"
    result = lc.load_loop_cache(store_env, loop_id, dest)

    assert result == dest
    assert (dest / lc.LATENTS_FILENAME).read_bytes() == b"latents-bytes"
    assert (dest / lc.COORDS_FILENAME).read_bytes() == b"coords-bytes"
    assert (dest / lc.MASK_COORDS_FILENAME).read_bytes() == b"mask-bytes"
    assert sorted(p.name for p in dest.iterdir()) == sorted(
        [lc.LATENTS_FILENAME, lc.COORDS_FILENAME, lc.MASK_COORDS_FILENAME]
    )


def test_load_loop_cache_miss_returns_none_and_leaves_dest_empty(store_env, tmp_path):
    dest = tmp_path / "restored"
    dest.mkdir()

    result = lc.load_loop_cache(store_env, "nonexistent-loop", dest)

    assert result is None
    assert list(dest.iterdir()) == []


def test_load_loop_cache_mask_optional(store_env, engine, session, tmp_path):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer())  # no mask written

    dest = tmp_path / "restored"
    result = lc.load_loop_cache(store_env, loop_id, dest)

    assert result == dest
    assert not (dest / lc.MASK_COORDS_FILENAME).exists()
    assert (dest / lc.LATENTS_FILENAME).exists()


def test_cache_is_present_false_when_object_deleted_then_rebuilds(store_env, engine, session):
    loop_id = _make_loop(session, store_env)
    lc.build_loop_cache(store_env, loop_id, FakePreparer())

    with Session(engine) as check:
        loop = check.get(BaseLoop, uuid.UUID(loop_id))
        assert lc.cache_is_present(store_env, loop) is True

    store_env.client.delete_object(Bucket=store_env.bucket, Key=lc.latents_key(loop_id))

    with Session(engine) as check2:
        loop2 = check2.get(BaseLoop, uuid.UUID(loop_id))
        assert lc.cache_is_present(store_env, loop2) is False  # stale column reads as a miss

    rebuilt = lc.build_loop_cache(store_env, loop_id, FakePreparer())
    assert rebuilt is True
