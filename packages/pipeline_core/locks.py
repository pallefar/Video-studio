"""Exclusive GPU lock. 24 GB fits one lane: the render lane (Chatterbox +
MuseTalk) and the Wan B-roll lane must never hold the GPU simultaneously.
Asserted by tests/test_gpu_exclusivity.py.

Redis SET NX with a TTL; release is compare-and-delete so a holder can only
release its own acquisition (a stale holder that outlived its TTL cannot
clobber the next one).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

GPU_LOCK_KEY = "gpu:exclusive"
DEFAULT_TTL_S = 3600  # renders are long; a crashed holder frees the GPU in an hour

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

HOLDER_RENDER = "render"
HOLDER_WAN = "wan"


class GpuLockHeld(Exception):
    def __init__(self, current_holder: str):
        self.current_holder = current_holder
        super().__init__(f"GPU is held by lane {current_holder!r}")


@contextmanager
def gpu_lock(redis, holder: str, ttl_s: int = DEFAULT_TTL_S) -> Iterator[None]:
    token = f"{holder}:{uuid.uuid4()}"
    if not redis.set(GPU_LOCK_KEY, token, nx=True, ex=ttl_s):
        current = redis.get(GPU_LOCK_KEY)
        current = current.decode() if isinstance(current, bytes) else (current or "unknown")
        raise GpuLockHeld(current.split(":", 1)[0])
    try:
        yield
    finally:
        redis.eval(_RELEASE_SCRIPT, 1, GPU_LOCK_KEY, token)
