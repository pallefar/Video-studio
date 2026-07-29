"""Stage dispatch onto the Redis queues.

Stage functions are referenced by import path so the API never imports worker
code. RQ job ids reuse stage_key, so what's queued is observable per
(job_id, stage).
"""

from __future__ import annotations

from typing import Optional

from pipeline_core.settings import Settings


def get_redis(settings: Optional[Settings] = None):
    from redis import Redis

    return Redis.from_url((settings or Settings()).redis_url)


class Dispatcher:
    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis(self._settings)
        return self._redis

    def enqueue(self, queue_name: str, func_path: str, *args: str, job_key: Optional[str] = None) -> None:
        from rq import Queue

        Queue(queue_name, connection=self.redis).enqueue(func_path, *args, job_id=job_key)
