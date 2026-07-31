"""Wan-lane worker entrypoint: generation + identity training (queue: wan).

A separate process from the render-lane worker by design — the two lanes
must never share a process, and the exclusive GPU lock (pipeline_core.locks)
keeps them off the card simultaneously. Same portability rules: addresses
from Settings, artefacts through ObjectStore, stages idempotent.
"""

from __future__ import annotations

import structlog

from pipeline_core.queues import GPU_WORKER_CONCURRENCY, QUEUE_WAN
from pipeline_core.settings import Settings

log = structlog.get_logger()

QUEUES = (QUEUE_WAN,)


def main() -> None:
    assert GPU_WORKER_CONCURRENCY == 1, "24 GB fits one lane — never parallel GPU workers"

    from redis import Redis
    from rq import Queue, Worker

    settings = Settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in QUEUES]
    log.info("wan_worker_boot", queues=list(QUEUES))
    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
