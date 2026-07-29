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
