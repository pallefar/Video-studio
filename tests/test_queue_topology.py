"""Queue topology invariants. The M3 assertion that a live GPU worker runs
with concurrency 1 builds on these constants; the render lane and the Wan
B-roll lane must already be distinct queues now."""

from __future__ import annotations

from pipeline_core.queues import (
    ALL_QUEUES,
    GPU_WORKER_CONCURRENCY,
    QUEUE_CPU,
    QUEUE_GPU,
    QUEUE_WAN,
    stage_key,
)


def test_gpu_concurrency_is_one():
    assert GPU_WORKER_CONCURRENCY == 1


def test_queues_are_distinct():
    assert len(set(ALL_QUEUES)) == len(ALL_QUEUES) == 3


def test_render_and_wan_lanes_are_separate():
    assert QUEUE_GPU != QUEUE_WAN


def test_gpu_worker_consumes_only_the_render_lane():
    from worker_gpu.run import QUEUES

    assert QUEUES == (QUEUE_GPU,)
    assert QUEUE_WAN not in QUEUES


def test_cpu_worker_consumes_only_the_cpu_lane():
    from worker_cpu.run import QUEUES

    assert QUEUES == (QUEUE_CPU,)


def test_stage_keys_are_idempotent_and_segment_scoped():
    job_id = "8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77"
    assert stage_key(job_id, "lipsync") == stage_key(job_id, "lipsync")
    assert stage_key(job_id, "tts", 3) == f"{job_id}:tts:3"
    assert stage_key(job_id, "tts", 3) != stage_key(job_id, "tts", 4)
    assert stage_key(job_id, "tts") != stage_key(job_id, "lipsync")
