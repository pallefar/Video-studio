"""The render lane and the Wan B-roll lane can never hold the GPU
simultaneously. Proven against a real Redis, both directions, including
release-on-exception and stale-holder safety."""

from __future__ import annotations

import pytest
from redis import Redis

from pipeline_core.locks import (
    GPU_LOCK_KEY,
    HOLDER_RENDER,
    HOLDER_WAN,
    GpuLockHeld,
    gpu_lock,
)


@pytest.fixture()
def redis(redis_url):
    client = Redis.from_url(redis_url)
    client.delete(GPU_LOCK_KEY)
    yield client
    client.delete(GPU_LOCK_KEY)


def test_render_blocks_wan(redis):
    with gpu_lock(redis, HOLDER_RENDER):
        with pytest.raises(GpuLockHeld) as excinfo:
            with gpu_lock(redis, HOLDER_WAN):
                pass
        assert excinfo.value.current_holder == HOLDER_RENDER


def test_wan_blocks_render(redis):
    with gpu_lock(redis, HOLDER_WAN):
        with pytest.raises(GpuLockHeld) as excinfo:
            with gpu_lock(redis, HOLDER_RENDER):
                pass
        assert excinfo.value.current_holder == HOLDER_WAN


def test_lanes_alternate_after_release(redis):
    with gpu_lock(redis, HOLDER_RENDER):
        pass
    with gpu_lock(redis, HOLDER_WAN):
        pass
    with gpu_lock(redis, HOLDER_RENDER):
        pass


def test_lock_released_on_exception(redis):
    with pytest.raises(RuntimeError):
        with gpu_lock(redis, HOLDER_RENDER):
            raise RuntimeError("engine crashed")
    with gpu_lock(redis, HOLDER_WAN):
        pass


def test_lock_has_a_ttl(redis):
    """A crashed holder that never releases must not brick the GPU forever."""
    with gpu_lock(redis, HOLDER_RENDER, ttl_s=1234):
        assert 0 < redis.ttl(GPU_LOCK_KEY) <= 1234


def test_stale_holder_cannot_release_the_next_lock(redis):
    """If holder A's TTL expired and B acquired, A's exit must not free B's lock."""
    lock_a = gpu_lock(redis, HOLDER_RENDER)
    lock_a.__enter__()
    redis.delete(GPU_LOCK_KEY)  # simulate A's TTL expiry
    with gpu_lock(redis, HOLDER_WAN):
        lock_a.__exit__(None, None, None)  # stale release attempt
        assert redis.get(GPU_LOCK_KEY) is not None, "stale holder clobbered the live lock"
