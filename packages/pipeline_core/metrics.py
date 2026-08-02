"""Stage duration metrics. Throughput regressions are how thermal throttling
shows up — every worker stage wraps itself in timed(). Recording must never
break the stage: failures are logged and swallowed.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Iterator

import structlog

log = structlog.get_logger()

# lipsync_stage's metric ref contract (consumed by scripts/bench.py::bench_loop).
# The writer (worker_gpu.stages.lipsync_stage) and the reader (bench_loop) must
# agree on exactly one ref format — this is the load-bearing shape, not a naming
# preference. A UUID's canonical form never contains a colon, so a colon
# separator plus the loop id can never collide with a job id, and a suffix
# match on it can never false-match a legacy (job-id-only) row or a different
# loop's row.
LIPSYNC_STAGE = "lipsync"
_LIPSYNC_REF_SEPARATOR = ":"


def lipsync_metric_ref(job_id: str, loop_id: str) -> str:
    """The ref a lipsync metric row is written under: names both the job that
    produced it and the loop it was rendered against. See lipsync_ref_suffix,
    the reader half of this contract."""
    return f"{job_id}{_LIPSYNC_REF_SEPARATOR}{loop_id}"


def lipsync_ref_suffix(loop_id: str) -> str:
    """The suffix scripts/bench.py::bench_loop matches a lipsync metric ref
    against to find every run recorded for one loop, regardless of which job
    produced it. Always a suffix of lipsync_metric_ref(<any job>, loop_id)."""
    return f"{_LIPSYNC_REF_SEPARATOR}{loop_id}"


def timed_stage(stage: str):
    """Decorator for worker stage functions whose first argument is the ref."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(ref, *args, **kwargs):
            with timed(stage, str(ref)):
                return fn(ref, *args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def timed(stage: str, ref: str) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            from pipeline_core.db import open_session
            from schema.models import Metric

            with open_session() as session:
                session.add(Metric(stage=stage, ref=ref, duration_ms=duration_ms))
                session.commit()
        except Exception as exc:  # metrics must never take a stage down
            log.warning("metric_write_failed", stage=stage, ref=ref, error=str(exc))
        log.info("stage_duration", stage=stage, ref=ref, duration_ms=duration_ms)
