"""GPU worker entrypoint. Single long-lived process, concurrency 1.

Runs natively in a venv, never in Docker on the workstation. Stateless and
portable to rented GPUs: every address comes from Settings (env), every
artefact moves through pipeline_core.storage.ObjectStore, and every stage is
idempotent on its stage_key. Models load once at boot (M3) and stay resident.
"""

from __future__ import annotations

import structlog

from pipeline_core.queues import GPU_WORKER_CONCURRENCY, QUEUE_GPU
from pipeline_core.settings import Settings

log = structlog.get_logger()

# The single queue this worker drains. The Wan B-roll lane (QUEUE_WAN) is a
# separate worker with an exclusive GPU lock — never listed here.
QUEUES = (QUEUE_GPU,)


def main() -> None:
    assert GPU_WORKER_CONCURRENCY == 1, "24 GB fits one lane — never parallel GPU workers"

    from redis import Redis
    from rq import Queue, Worker

    settings = Settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in QUEUES]
    log.info("gpu_worker_boot", queues=list(QUEUES))

    # M3.1: models load once at boot and stay resident — never lazily inside
    # the first job. Lazy loading made the first real job pay full multi-GB
    # model-load latency inline, and a worker that never receives a job
    # never proved its models load at all. Any load failure propagates
    # here: a worker that cannot load its models must never start consuming
    # jobs it would otherwise silently fail.
    from worker_gpu.stages import get_engines

    log.info("gpu_worker_warming_start")
    tts_engine, lipsync_engine = get_engines()
    log.info(
        "gpu_worker_warming_done",
        tts_engine=type(tts_engine).__name__,
        lipsync_engine=type(lipsync_engine).__name__,
    )

    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
