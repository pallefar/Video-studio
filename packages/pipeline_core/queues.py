"""Queue topology constants and idempotency keys.

The GPU render lane and the Wan B-roll lane are separate queues and are never
concurrent — 24 GB fits one lane. GPU worker concurrency is 1, asserted by
tests/test_queue_topology.py.
"""

from __future__ import annotations

import uuid
from typing import Optional

QUEUE_GPU = "gpu"
QUEUE_CPU = "cpu"
QUEUE_WAN = "wan"

ALL_QUEUES = (QUEUE_GPU, QUEUE_CPU, QUEUE_WAN)

GPU_WORKER_CONCURRENCY = 1


def stage_key(job_id: uuid.UUID | str, stage: str, segment_idx: Optional[int] = None) -> str:
    """Idempotency key for a pipeline stage.

    Every stage is idempotent on (job_id, stage); segment-level TTS refines
    the stage to tts:{idx} so one bad sentence re-renders alone.
    """
    suffix = f"{stage}:{segment_idx}" if segment_idx is not None else stage
    return f"{job_id}:{suffix}"
