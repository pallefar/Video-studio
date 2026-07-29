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
    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
