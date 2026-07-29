"""CPU worker entrypoint: ffmpeg assembly stages. Parallelisable, no GPU.

Same portability rules as the GPU worker: addresses from Settings (env),
artefacts through ObjectStore, stages idempotent on their stage_key.
"""

from __future__ import annotations

import structlog

from pipeline_core.queues import QUEUE_CPU
from pipeline_core.settings import Settings

log = structlog.get_logger()

QUEUES = (QUEUE_CPU,)


def main() -> None:
    from redis import Redis
    from rq import Queue, Worker

    settings = Settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in QUEUES]
    log.info("cpu_worker_boot", queues=list(QUEUES))
    worker = Worker(queues, connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
